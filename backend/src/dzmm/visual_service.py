"""Visual generation service: ComfyUI as an independent API consumer.

Architecture decision (2026-10-09): ComfyUI stays a standalone project —
DZMM only configures its address, imports workflow JSON, injects
prompt/seed, and downloads resulting images. No models, no workflow
runtime, no node management bundled here.

M1 scope: settings persistence, connection status, fire-and-forget
generation tasks (concurrency 1), media records, media file serving.
Trigger closure (world creation / turn completion hooks) lands in M2.
"""

from __future__ import annotations

import asyncio
import json
import random
import re
import urllib.error
import urllib.request
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from . import comfy_client
from .config import Settings
from .persistence import heroes, runs, turns, visual_media, world_versions
from .visual_pipeline import (
    DEFAULT_NEGATIVE,
    DEFAULT_STYLE_PREFIX,
    build_img2img_workflow,
    build_prompt,
    build_txt2img_workflow,
    load_workflow_template,
    save_media,
    visual_card_from,
)

SETTINGS_FILENAME = "visual_settings.json"
MEDIA_DIRNAME = "media"
SAFE_WORLD_ID = re.compile(r"^[0-9a-fA-F-]{6,64}$")
SAFE_FILENAME = re.compile(r"^[A-Za-z0-9._-]{1,200}$")


class VisualSettingsError(ValueError):
    pass


class VisualSettings(BaseModel):
    comfy_url: str = "http://127.0.0.1:8188"
    enabled: bool = False
    style_prefix: str = DEFAULT_STYLE_PREFIX
    negative_prompt: str = DEFAULT_NEGATIVE
    # 空 = 使用内置 SDXL 模板；非空指向 ComfyUI 导出的 API 格式 JSON
    workflow_txt2img_path: str = ""
    workflow_img2img_path: str = ""
    max_concurrency: int = Field(default=1, ge=1, le=4)
    auto_portraits: bool = True
    auto_cover: bool = True
    auto_locations: bool = True
    auto_scenes: bool = True

    def validate(self) -> None:
        if not self.comfy_url.startswith(("http://", "https://")):
            raise VisualSettingsError("comfy_url 必须以 http:// 或 https:// 开头")
        if not self.style_prefix.strip():
            raise VisualSettingsError("style_prefix 不能为空（作为全局画风兜底）")


class VisualGenerateInput(BaseModel):
    world_id: str
    kind: Literal["portrait", "location", "cover", "scene"]
    subject_id: str = ""
    scene_note: str = ""
    # media 目录内相对路径；提供时走 img2img 延续基准图
    ref_image: str = ""
    # scene 自动参考：取该地点在场角色的最新基准立绘（≤2）
    location_id: str = ""
    seed: int | None = None
    turn_seq: int | None = None


class VisualService:
    """Owns visual settings, the generation queue, and media records."""

    def __init__(self, session_factory: async_sessionmaker, settings: Settings) -> None:
        self._sessions = session_factory
        self._settings = settings
        self._visual_settings: VisualSettings | None = None
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._worker: asyncio.Task | None = None

    # ---- settings ----

    @property
    def settings_path(self) -> Path:
        return self._settings.data_dir / SETTINGS_FILENAME

    def get_settings(self) -> VisualSettings:
        if self._visual_settings is None:
            path = self.settings_path
            if path.exists():
                data = json.loads(path.read_text(encoding="utf-8"))
                self._visual_settings = VisualSettings(**data)
            else:
                self._visual_settings = VisualSettings()
        return self._visual_settings

    def update_settings(self, payload: VisualSettings) -> VisualSettings:
        payload.validate()
        self.settings_path.write_text(
            payload.model_dump_json(indent=2), encoding="utf-8"
        )
        self._visual_settings = payload
        return payload

    @property
    def media_dir(self) -> Path:
        return self._settings.data_dir / MEDIA_DIRNAME

    # ---- status ----

    async def status(self) -> dict[str, Any]:
        vs = self.get_settings()
        reachable, detail = await asyncio.to_thread(self._probe_comfyui, vs.comfy_url)
        return {
            "comfy_url": vs.comfy_url,
            "enabled": vs.enabled,
            "reachable": reachable,
            "detail": detail,
            "queued": self._queue.qsize(),
        }

    @staticmethod
    def _probe_comfyui(base_url: str) -> tuple[bool, str]:
        try:
            request = urllib.request.Request(
                f"{base_url.rstrip('/')}/system_stats", method="GET"
            )
            with urllib.request.urlopen(request, timeout=3) as response:
                payload = json.loads(response.read().decode("utf-8"))
            return True, str(payload.get("system", {}).get("comfyui_version", "unknown"))
        except (OSError, urllib.error.URLError, ValueError) as error:
            return False, f"ComfyUI 不可达：{error}"

    # ---- generation ----

    async def generate(self, payload: VisualGenerateInput) -> dict[str, Any]:
        vs = self.get_settings()
        if not vs.enabled:
            raise VisualDisabledError("视觉功能未开启（设置页 → 视觉）")

        definition = await self._latest_world_definition(payload.world_id)
        hero = await self._hero_for_portrait(payload, definition)
        prompt_fragments, fallback_seed = self._resolve_prompt(
            payload, definition, hero=hero
        )
        seed = (
            payload.seed
            if payload.seed is not None
            else (fallback_seed if fallback_seed else random.randint(1, 2**31 - 1))
        )
        prompt = build_prompt(
            style_prefix=vs.style_prefix,
            fragments=prompt_fragments,
            scene_note=payload.scene_note if payload.kind == "scene" else "",
        )
        ref_image = payload.ref_image
        if payload.kind == "scene" and not ref_image and payload.location_id:
            ref_image = await self._latest_portrait_ref(
                payload.world_id, definition, payload.location_id
            )

        record_id = uuid.uuid4().hex
        now = datetime.now(UTC).replace(tzinfo=None)
        async with self._sessions() as session, session.begin():
            await session.execute(
                visual_media.insert().values(
                    id=record_id,
                    world_id=payload.world_id,
                    kind=payload.kind,
                    subject_id=payload.subject_id,
                    turn_seq=payload.turn_seq,
                    file_path=None,
                    prompt=prompt,
                    negative_prompt=vs.negative_prompt,
                    seed=seed,
                    ref_image=ref_image or None,
                    status="queued",
                    error=None,
                    created_at=now,
                )
            )
        self._ensure_worker()
        self._queue.put_nowait(record_id)
        return await self.task(record_id)

    async def task(self, task_id: str) -> dict[str, Any]:
        async with self._sessions() as session:
            row = (
                await session.execute(
                    select(visual_media).where(visual_media.c.id == task_id)
                )
            ).mappings().one_or_none()
        if row is None:
            raise VisualTaskNotFoundError(f"visual task not found: {task_id}")
        return self._serialize(row)

    @staticmethod
    def _serialize(row: Any) -> dict[str, Any]:
        return {
            key: (value.isoformat() if isinstance(value, datetime) else value)
            for key, value in dict(row).items()
        }

    def _ensure_worker(self) -> None:
        if self._worker is None or self._worker.done():
            self._worker = asyncio.create_task(
                self._run_worker(), name="dzmm-visual-worker"
            )

    async def _run_worker(self) -> None:
        while True:
            task_id = await self._queue.get()
            try:
                await self._process(task_id)
            except asyncio.CancelledError:
                raise
            except Exception as error:  # noqa: BLE001 — 任务必须收敛为 failed
                await self._mark_failed(task_id, str(error))
            finally:
                self._queue.task_done()

    async def _process(self, task_id: str) -> None:
        record = await self.task(task_id)
        vs = self.get_settings()
        await self._update_status(task_id, "running")

        try:
            if record["ref_image"]:
                template = load_workflow_template(
                    "img2img", vs.workflow_img2img_path or None
                )
                workflow = build_img2img_workflow(
                    template,
                    positive_prompt=record["prompt"],
                    negative_prompt=record["negative_prompt"],
                    seed=record["seed"],
                    reference_image_filename=Path(record["ref_image"]).name,
                )
            else:
                template = load_workflow_template(
                    "txt2img", vs.workflow_txt2img_path or None
                )
                workflow = build_txt2img_workflow(
                    template,
                    positive_prompt=record["prompt"],
                    negative_prompt=record["negative_prompt"],
                    seed=record["seed"],
                )

            _, image_blobs = await asyncio.to_thread(
                comfy_client.generate, vs.comfy_url, workflow
            )
            if not image_blobs:
                raise comfy_client.ComfyUIError("ComfyUI 未返回任何图片")
            # 并发上限 1：一张工作流可能返回多图，但每任务只落第一张
            path = await asyncio.to_thread(
                save_media,
                self.media_dir,
                record["world_id"],
                image_blobs[0],
                kind=record["kind"],
                subject_id=record["subject_id"] or record["kind"],
            )
            relative = path.relative_to(self.media_dir).as_posix()
            await self._complete(task_id, relative)
        except BaseException:
            await self._update_status(task_id, "failed")
            raise

    async def _latest_world_definition(self, world_id: str) -> dict[str, Any]:
        async with self._sessions() as session:
            row = (
                await session.execute(
                    select(world_versions.c.definition)
                    .where(world_versions.c.world_id == world_id)
                    .order_by(world_versions.c.version_number.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
        if row is None:
            raise VisualWorldNotFoundError(f"world not found: {world_id}")
        return row

    async def _hero_for_portrait(
        self, payload: VisualGenerateInput, definition: dict[str, Any]
    ) -> dict[str, Any] | None:
        """主角立绘的降级数据源：subject 不在 character_cards 时查 heroes 表。"""

        if payload.kind != "portrait" or not payload.subject_id.strip():
            return None
        for card in definition.get("character_cards") or []:
            if card.get("id") == payload.subject_id:
                return None
        async with self._sessions() as session:
            row = (
                await session.execute(
                    select(heroes.c.name, heroes.c.profile).where(
                        heroes.c.id == payload.subject_id
                    )
                )
            ).mappings().one_or_none()
        return dict(row) if row else None

    @staticmethod
    def _resolve_prompt(
        payload: VisualGenerateInput,
        definition: dict[str, Any],
        hero: dict[str, Any] | None = None,
    ) -> tuple[list[str], int | None]:
        """Map (kind, subject_id) to prompt fragments + optional fixed seed.

        M1/M2 使用世界定义已有的文本（visual.appearance、npc description、
        名称）；LLM 外貌卡生成是后续增强。
        """

        if payload.kind == "cover":
            return [str(definition.get("name") or "世界封面")], None

        subject_id = payload.subject_id.strip()
        if payload.kind == "scene":
            if not payload.scene_note.strip():
                raise VisualInputError("scene 生成必须提供 scene_note")
            return [], None

        if not subject_id:
            raise VisualInputError(f"{payload.kind} 生成必须提供 subject_id")

        if payload.kind == "portrait":
            for card in definition.get("character_cards") or []:
                if card.get("id") != subject_id:
                    continue
                visual = visual_card_from(card)
                description = _npc_description(definition, subject_id)
                return _fragment(visual, card, description), visual.seed or None
            if hero is not None:
                profile_bits = [
                    str(value)
                    for value in (hero.get("profile") or {}).values()
                    if isinstance(value, str)
                ]
                return [", ".join([str(hero.get("name") or ""), *profile_bits])], None
            raise VisualInputError(f"character_card 不存在：{subject_id}")

        for location in definition.get("locations") or []:
            if location.get("id") != subject_id:
                continue
            visual = visual_card_from(location)
            return _fragment(visual, location), visual.seed or None
        raise VisualInputError(f"location 不存在：{subject_id}")

    async def _update_status(self, task_id: str, status: str) -> None:
        async with self._sessions() as session, session.begin():
            await session.execute(
                visual_media.update()
                .where(visual_media.c.id == task_id)
                .values(status=status)
            )

    async def _complete(self, task_id: str, file_path: str) -> None:
        async with self._sessions() as session, session.begin():
            await session.execute(
                visual_media.update()
                .where(visual_media.c.id == task_id)
                .values(status="done", file_path=file_path)
            )

    async def _mark_failed(self, task_id: str, error: str) -> None:
        async with self._sessions() as session, session.begin():
            await session.execute(
                visual_media.update()
                .where(visual_media.c.id == task_id)
                .values(status="failed", error=error[:2000])
            )

    async def aclose(self) -> None:
        if self._worker is not None:
            self._worker.cancel()
            try:
                await self._worker
            except asyncio.CancelledError:
                pass
            self._worker = None

    # ---- 触发闭环（M2）：世界创建批量生成 + 回合场景插画 ----

    async def after_compose(self, world_id: str, hero_id: str) -> None:
        """世界创建成功后的异步批量生成；单张失败只记 registry 不中断。"""

        vs = self.get_settings()
        if not vs.enabled:
            return
        try:
            definition = await self._latest_world_definition(world_id)
        except LookupError:
            return

        jobs: list[tuple[str, str]] = []
        if vs.auto_cover:
            jobs.append(("cover", ""))
        if vs.auto_portraits:
            jobs.append(("portrait", hero_id))
            for card in (definition.get("character_cards") or [])[:4]:
                subject = str(card.get("id") or "").strip()
                if subject:
                    jobs.append(("portrait", subject))
        if vs.auto_locations:
            for location in (definition.get("locations") or [])[:3]:
                subject = str(location.get("id") or "").strip()
                if subject:
                    jobs.append(("location", subject))

        for kind, subject_id in jobs:
            try:
                await self.generate(
                    VisualGenerateInput(
                        world_id=world_id, kind=kind, subject_id=subject_id
                    )
                )
            except (LookupError, ValueError, RuntimeError):
                continue  # 失败已落 visual_media(status=failed)，UI 据此显示重摇

    async def after_turn(self, run_id: str) -> None:
        """回合结算后的场景插画；取最新回合，失败静默（不阻塞下一回合）。"""

        vs = self.get_settings()
        if not vs.enabled or not vs.auto_scenes:
            return
        async with self._sessions() as session:
            turn_row = (
                await session.execute(
                    select(turns.c.sequence)
                    .where(turns.c.run_id == run_id)
                    .order_by(turns.c.sequence.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
        if turn_row is None:
            return
        try:
            await self.scene_for_turn(run_id, int(turn_row))
        except (LookupError, ValueError, RuntimeError):
            return

    async def scene_for_turn(self, run_id: str, sequence: int) -> dict[str, Any]:
        """为一回合生成场景插画（自动触发与手动补生成的共用实现）。"""

        vs = self.get_settings()
        if not vs.enabled:
            raise VisualDisabledError("视觉功能未开启（设置页 → 视觉）")

        async with self._sessions() as session:
            run_row = (
                await session.execute(
                    select(runs.c.world_version_id, runs.c.state).where(
                        runs.c.id == run_id
                    )
                )
            ).mappings().one_or_none()
            if run_row is None:
                raise VisualWorldNotFoundError(f"run not found: {run_id}")
            world_id = (
                await session.execute(
                    select(world_versions.c.world_id).where(
                        world_versions.c.id == run_row["world_version_id"]
                    )
                )
            ).scalar_one_or_none()
            turn_row = (
                await session.execute(
                    select(turns.c.narrative)
                    .where(
                        (turns.c.run_id == run_id) & (turns.c.sequence == sequence)
                    )
                )
            ).scalar_one_or_none()
        if world_id is None:
            raise VisualWorldNotFoundError("run has no world version")
        if turn_row is None:
            raise VisualTaskNotFoundError(f"turn not found: {run_id}#{sequence}")

        scene_note = str(turn_row or "").strip()[:240]
        location_id = str((run_row["state"] or {}).get("location_id") or "")
        return await self.generate(
            VisualGenerateInput(
                world_id=world_id,
                kind="scene",
                subject_id=run_id,
                scene_note=scene_note or f"{run_id} 第 {sequence} 回合",
                location_id=location_id,
                turn_seq=sequence,
            )
        )

    async def list_media(
        self,
        world_id: str,
        *,
        kind: str | None = None,
        subject_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """世界维度媒体列表：UI 发现图片与判断「生成中/失败可重摇」。"""

        query = select(visual_media).where(visual_media.c.world_id == world_id)
        if kind:
            query = query.where(visual_media.c.kind == kind)
        if subject_id:
            query = query.where(visual_media.c.subject_id == subject_id)
        query = query.order_by(visual_media.c.created_at.desc(), visual_media.c.id)
        async with self._sessions() as session:
            rows = (await session.execute(query)).mappings().all()
        return [self._serialize(row) for row in rows]

    async def _latest_portrait_ref(
        self, world_id: str, definition: dict[str, Any], location_id: str
    ) -> str:
        """在场角色（≤2）最新的完成立绘 → img2img 基准图路径；没有则空。"""

        npc_ids = [
            str(npc.get("id"))
            for npc in definition.get("npcs") or []
            if str(npc.get("location_id") or "") == location_id and npc.get("id")
        ][:2]
        if not npc_ids:
            return ""
        async with self._sessions() as session:
            row = (
                await session.execute(
                    select(visual_media.c.file_path)
                    .where(
                        (visual_media.c.world_id == world_id)
                        & (visual_media.c.kind == "portrait")
                        & (visual_media.c.status == "done")
                        & (visual_media.c.subject_id.in_(npc_ids))
                    )
                    .order_by(
                        visual_media.c.created_at.desc(), visual_media.c.id.desc()
                    )
                    .limit(1)
                )
            ).scalar_one_or_none()
        return str(row or "")


class VisualDisabledError(RuntimeError):
    pass


class VisualWorldNotFoundError(LookupError):
    pass


class VisualTaskNotFoundError(LookupError):
    pass


class VisualInputError(ValueError):
    pass


def _npc_description(definition: dict[str, Any], subject_id: str) -> str:
    for npc in definition.get("npcs") or []:
        if npc.get("id") == subject_id:
            return str(npc.get("description") or "")
    return ""


def _fragment(
    visual: Any,
    entry: dict[str, Any],
    fallback_description: str = "",
) -> list[str]:
    appearance = visual.appearance or fallback_description
    parts = [part for part in (visual.prompt_fragment(), appearance) if part]
    if not parts:
        parts = [str(entry.get("name") or "")]
    return parts
