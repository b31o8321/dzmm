"""结局后接续新 Run，补满每题材累计 30 回合叙事（验证器缺口①）。"""
import json, sys, time, urllib.request, uuid

BASE = "http://127.0.0.1:8801"
PROFILE_NAME = "Mac qwen2.5-32k"
TARGET = 30
OUT = "/tmp/score_runs"

def api(path, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(f"{BASE}/api/v2{path}", data=data,
        headers={"content-type": "application/json"},
        method="POST" if payload is not None else "GET")
    with urllib.request.urlopen(request, timeout=420) as response:
        return json.loads(response.read().decode())

def log(key, msg):
    print(f"[{key}] {msg}", flush=True)

def play_turns(run_id, start_turn, target, key, tag):
    """在新 Run 里玩到 target 累计回合或结局；返回 (turns, story, done)。"""
    turns = []
    story = {}
    run = api(f"/runs/{run_id}")
    revision = run["state"]["revision"]
    story = run["state"]
    turn_no = start_turn
    while turn_no <= target:
        chapter = story.get("chapter") or {}
        resolved = set(chapter.get("resolved_choice_ids") or [])
        # 新 Run 的 definition 从 run 里拿不到 story.chapters？run.state 有 chapter。
        # 通过 /runs/{id} 不含 definition；改从 choice 列表缺失时 fallback narrate。
        # 尝试：直接用自由行动为主，偶发 narrate；choices 端点在主 Run 已验证。
        if turn_no % 5 == 0:
            player_input = "我不按选项来：主动向在场的人打听一件让我在意的小事。"
            payload = {"expected_revision": revision, "player_input": player_input,
                       "commands": [{"type": "narrate", "payload": {}}]}
            status, result = _post(f"/runs/{run_id}/turns", {"request_id": f"{key}-c{turn_no}-{uuid.uuid4().hex[:4]}", **payload})
        else:
            payload = {"expected_revision": revision, "player_input": "继续推进当前目标。",
                       "commands": [{"type": "narrate", "payload": {}}]}
            status, result = _post(f"/runs/{run_id}/turns", {"request_id": f"{key}-c{turn_no}-{uuid.uuid4().hex[:4]}", **payload})
        if status not in (200, 201):
            log(key, f"turn {turn_no} status={status}")
            return turns, story, False
        revision = result["state"]["revision"]
        story = result["state"]
        turns.append({"turn": turn_no, "narrative": result["narrative"],
                      "chapter": (story.get("chapter") or {}).get("id"),
                      "ending": story.get("ending"), "outcomes": result["outcomes"]})
        if story.get("ending"):
            return turns, story, True
        turn_no += 1
    return turns, story, False

def _post(path, payload, retries=2):
    data = json.dumps(payload).encode()
    for attempt in range(retries + 1):
        request = urllib.request.Request(f"{BASE}/api/v2{path}", data=data,
            headers={"content-type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=420) as response:
                return response.status, json.loads(response.read().decode())
        except urllib.error.HTTPError as error:
            return error.code, {}
        except (TimeoutError, urllib.error.URLError, OSError) as error:
            log("post", f"attempt {attempt+1} transport error: {error}")
            time.sleep(5)
    return 0, {}

def warmup():
    try:
        urllib.request.urlopen(urllib.request.Request(
            "http://127.0.0.1:11434/api/chat",
            data=json.dumps({"model": "qwen2.5:7b-32k", "messages": [
                {"role": "user", "content": "回复：好"}],
                "stream": False, "options": {"num_predict": 8}}).encode(),
            headers={"content-type": "application/json"}), timeout=240)
    except Exception as error:
        log("warmup", f"{error}")


def main():
    warmup()
    worlds = api("/worlds")
    targets = {"钟声之城": "mystery", "末日深空": "survival",
               "权谋之巅": "intrigue", "夜市金牌食肆": "nightmarket"}
    for world in worlds:
        key = targets.get(world["name"])
        if not key:
            continue
        record = json.load(open(f"{OUT}/{key}.json"))
        have = record["completed_turns"]
        if have >= TARGET:
            log(key, f"already {have} turns, skip")
            continue
        log(key, f"continuing from {have} turns")
        # 找该世界最新 world_version 与其上已完成 Run 的 profile
        runs_of_world = api(f"/worlds/{world['id']}/runs") if False else None
        # 直接从 world 详情拿 world_version
        world_detail = api(f"/worlds/{world['id']}")
        version_id = world_detail.get("latest_world_version_id") or world_detail.get("world_version_id")
        profile_id = None
        # 用已存在档案
        profiles = api("/model-profiles")
        profile_id = next(p["id"] for p in profiles if p["model_name"] == "qwen2.5:7b-32k")
        new_prefix = f"{key}-cont"
        new_run = api(f"/worlds/{world['id']}/runs", {
            "request_id": f"{new_prefix}-{uuid.uuid4().hex[:6]}",
            "hero": {"name": f"续行者{key[:3]}", "profile": {}},
            "model_profile_id": profile_id})
        run2_id = new_run["run_id"]
        revision = new_run["state"]["revision"]
        story = new_run["state"]
        log(key, f"continuation run={run2_id[:8]}")
        turn_no = have + 1
        added = []
        while turn_no <= TARGET:
            payload = {"expected_revision": revision, "player_input": "继续推进当前目标。",
                       "commands": [{"type": "narrate", "payload": {}}]}
            status, result = _post(f"/worlds/../runs/{run2_id}/turns" if False else f"/runs/{run2_id}/turns",
                                   {"request_id": f"{new_prefix}-t{turn_no}-{uuid.uuid4().hex[:4]}", **payload})
            if status not in (200, 201):
                log(key, f"turn {turn_no} status={status}")
                break
            revision = result["state"]["revision"]
            story = result["state"]
            added.append({"turn": turn_no, "narrative": result["narrative"],
                          "chapter": (story.get("chapter") or {}).get("id"),
                          "ending": story.get("ending"), "outcomes": result["outcomes"],
                          "continuation": True})
            if story.get("ending"):
                log(key, f"continuation reached ending at {turn_no}")
                break
            turn_no += 1
        record["turns"].extend(added)
        record["completed_turns"] = len(record["turns"])
        record["second_run_turns"] = len(added)
        (open(f"{OUT}/{key}.json", "w")).write(json.dumps(record, ensure_ascii=False, indent=1))
        log(key, f"now {record['completed_turns']}/30 (+{len(added)} continuation)")

main()
