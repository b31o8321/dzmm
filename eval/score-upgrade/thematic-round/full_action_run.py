"""v1.9.0 全动作驱动（Phase 1/3）：narrate/move/skill/inventory/choose 混合轮换 + 12 维指标。

用法：THEMATIC_BASE=... python3 full_action_run.py <world.json> <turns> <profile_id>
"""
import json, os, sys, time, urllib.request, uuid

BASE = os.environ.get("THEMATIC_BASE", "http://127.0.0.1:8908/api/v2")

def api(path, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(f"{BASE}{path}", data=data,
        headers={"content-type": "application/json"},
        method="POST" if payload is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=360) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode() or "{}")
    except (TimeoutError, urllib.error.URLError) as e:
        return 0, {"detail": f"client timeout: {e}"}

def log(m): print(m, flush=True)

world_file, turns_n, profile_id = sys.argv[1], int(sys.argv[2]), sys.argv[3]
bundle = json.load(open(world_file, encoding="utf-8"))
mode = os.path.basename(world_file).replace(".json", "")
wd = bundle["world_definition"]
location_ids = [loc["id"] for loc in wd["locations"]]
resource_ids = [r["id"] for r in wd.get("resources", [])]
enemy = next((n for n in wd.get("npcs", []) if isinstance(n.get("combat"), dict)), None)
enemy_id, enemy_defeated = (enemy["id"] if enemy else None), False

_status, composed = api("/worlds:compose", {
    "request_id": f"fa-{mode}-{uuid.uuid4().hex[:6]}",
    "world_definition": wd, "hero": bundle["hero"], "model_profile_id": profile_id})
if composed.get("state") is None:
    log(f"compose FAIL: {json.dumps(composed, ensure_ascii=False)[:200]}"); sys.exit(1)
run_id = composed["run_id"]
rev = composed["state"]["revision"]
log(f"[{mode}] composed run={run_id}")

done, fails = 0, 0
metrics = {
    "locations_visited": {composed["state"]["location_id"]},
    "moves": 0, "skill_checks": 0, "skill_success": 0,
    "inventory_changes": 0, "inventory_final": None,
    "npc_dialogue_turns": 0, "quest_completed": 0,
    "attacks": 0, "attack_hits": 0, "enemy_defeated": False,
    "ending": None, "clock_trace": [], "chars_total": 0, "secs_total": 0.0,
}

for i in range(turns_n):
    cmds = [{"type": "narrate", "payload": {}}]
    phase = i % 4
    if phase == 1 and len(location_ids) > 1:
        # 轮换地点
        target = location_ids[i % len(location_ids)]
        cur = metrics.get("_cur_loc")
        if target != cur:
            cmds = [{"type": "move", "payload": {"location_id": target}}, {"type": "narrate", "payload": {}}]
    elif phase == 2 and resource_ids:
        # 技能检定或道具操作（轮换）
        if i % 8 == 2:
            cmds = [{"type": "skill_check", "payload": {"skill": "insight", "dc": 12}},
                    {"type": "narrate", "payload": {}}]
        else:
            cmds = [{"type": "inventory_change", "payload": {"item_id": resource_ids[0], "delta": 1}},
                    {"type": "narrate", "payload": {}}]
    elif phase == 3 and enemy_id and not enemy_defeated:
        # 战斗轮换：攻击敌对 NPC 直到倒下
        cmds = [{"type": "attack", "payload": {"target_id": enemy_id}},
                {"type": "narrate", "payload": {}}]
    # phase 0 纯 narrate

    t0 = time.time()
    status, body = api(f"/runs/{run_id}/turns", {
        "request_id": f"fa-{mode}-t{i}", "expected_revision": rev,
        "player_input": f"第{i+1}次行动，我继续探索。",
        "commands": cmds})
    elapsed = round(time.time() - t0, 1)
    if body.get("state") is None:
        fails += 1
        log(f"turn{i}: FAIL({status}) {json.dumps(body, ensure_ascii=False)[:140]}")
        if status == 409 and "expected_revision" in json.dumps(body):
            _, fresh = api(f"/runs/{run_id}")
            rev = fresh["state"]["revision"]
        continue
    rev = body["state"]["revision"]
    st = body["state"]
    narrative = body.get("narrative") or ""
    metrics["locations_visited"].add(st.get("location_id"))
    metrics["clock_trace"].append(st["clock"]["now_minutes"] if st.get("clock") else None)
    metrics["chars_total"] += len(narrative)
    metrics["secs_total"] += elapsed
    for o in body.get("outcomes", []):
        t = o.get("type")
        if t == "move": metrics["moves"] += 1
        elif t == "skill_check_result":
            metrics["skill_checks"] += 1
            if o.get("success"): metrics["skill_success"] += 1
        elif t == "inventory_changed": metrics["inventory_changes"] += 1
        elif t == "quest_completed": metrics["quest_completed"] += 1
        elif t == "attack":
            metrics["attacks"] += 1
            if o.get("hit"): metrics["attack_hits"] += 1
            if o.get("defeated"): enemy_defeated = True
    if "「" in narrative or "：”" in narrative or '“' in narrative:
        metrics["npc_dialogue_turns"] += 1
    if st.get("ending"):
        metrics["ending"] = st["ending"]
        log(f"ending@{i}: {st['ending'].get('id')}")
        done += 1
        break
    done += 1
    log(f"turn{i}: rev={rev} loc={st.get('location_id')} clock={metrics['clock_trace'][-1]} chars={len(narrative)} {elapsed}s")
    time.sleep(1)

metrics["locations_visited"] = sorted(metrics["locations_visited"])
metrics["inventory_final"] = composed and api(f"/runs/{run_id}")[1]["state"].get("inventory")
metrics["done"] = done; metrics["failures"] = fails; metrics["requested"] = turns_n
out = f"/Users/norman/development/dzmm/eval/score-upgrade/thematic-round/fullaction-{mode}-result.json"
json.dump(metrics, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=str)
log(f"METRICS: {json.dumps({k: metrics[k] for k in ('done','failures','moves','skill_checks','locations_visited','quest_completed','ending')}, ensure_ascii=False, default=str)}")
