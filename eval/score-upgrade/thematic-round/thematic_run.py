"""多题材多回合测试驱动（v1.8 测试轮）。

用法：python3 thematic_run.py <world.json> <turns> <profile_id>
环境变量：THEMATIC_BASE（默认 8906）
指标：成功/失败、时钟轨迹、开头重复、结局、蒸馏就绪。
"""
import json, os, sys, time, urllib.request, uuid

BASE = os.environ.get("THEMATIC_BASE", "http://127.0.0.1:8906/api/v2")

def api(path, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(f"{BASE}{path}", data=data,
        headers={"content-type": "application/json"},
        method="POST" if payload is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=600) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode() or "{}")

def log(m): print(m, flush=True)

world_file, turns_n, profile_id = sys.argv[1], int(sys.argv[2]), sys.argv[3]
bundle = json.load(open(world_file, encoding='utf-8'))
mode = os.path.basename(world_file).replace('.json', '')

_status, composed = api("/worlds:compose", {
    "request_id": f"th-{mode}-{uuid.uuid4().hex[:6]}",
    "world_definition": bundle["world_definition"],
    "hero": bundle["hero"], "model_profile_id": profile_id})
if composed.get("state") is None:
    log(f"compose FAIL: {json.dumps(composed, ensure_ascii=False)[:200]}"); sys.exit(1)
run_id = composed["run_id"]
rev = composed["state"]["revision"]
log(f"[{mode}] composed run={run_id}")

inputs = [
    "我沿着熟悉又陌生的路往前走，留意任何不对劲的细节。",
    "我主动和眼前的人搭话，试探他们知道多少。",
    "我回头检查刚才走过的位置，确认时间是否还在流动。",
    "我拿出随身的东西检查状态，并清点可用资源。",
    "我尝试做一件上一轮没有做过的新事情。",
    "我观察周围人的表情，找出谁在隐瞒什么。",
    "我朝深处走，把关键地点再搜一遍。",
    "我把目前掌握的线索在心里串一遍，做出决断。",
]
done, fails, clocks, opens, narrative_by_turn, ending_seen = 0, 0, [], [], [], None
for i in range(turns_n):
    text = inputs[i % len(inputs)]
    cmds = [{"type": "narrate", "payload": {}}]
    t0 = time.time()
    status, body = api(f"/runs/{run_id}/turns", {
        "request_id": f"th-{mode}-t{i}", "expected_revision": rev,
        "player_input": text, "commands": cmds})
    elapsed = round(time.time() - t0, 1)
    if body.get("state") is None:
        fails += 1
        log(f"turn{i}: FAIL({status}) {json.dumps(body, ensure_ascii=False)[:140]}")
        if status == 409 and "expected_revision" in json.dumps(body):
            _, fresh = api(f"/runs/{run_id}")
            rev = fresh["state"]["revision"]
        continue
    rev = body["state"]["revision"]
    narrative = body.get("narrative") or ""
    clock = body["state"].get("clock") or {}
    clocks.append(clock.get("now_minutes"))
    opens.append("".join(narrative.split())[:12])
    narrative_by_turn.append({"turn": i, "narrative": narrative[:400], "chars": len(narrative), "secs": elapsed})
    done += 1
    log(f"turn{i}: rev={rev} clock={clock.get('now_minutes')} chars={len(narrative)} {elapsed}s")
    if body["state"].get("ending"):
        ending_seen = body["state"]["ending"]
        log(f"ending@{i}: {ending_seen.get('id')}")
        break
    time.sleep(1)

repeats = sum(1 for i in range(1, len(opens)) if opens[i] and opens[i] in opens[max(0, i-4):i])
out = {"mode": mode, "requested": turns_n, "done": done, "failures": fails,
       "opening_repeats_recent4": repeats, "clock_trace": clocks,
       "ending": ending_seen, "turns": narrative_by_turn}
json.dump(out, open(f"/Users/norman/development/dzmm/eval/score-upgrade/thematic-round/{mode}-result.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
log(f"METRICS: {json.dumps({k: out[k] for k in ('mode','done','failures','opening_repeats_recent4','ending')}, ensure_ascii=False)}")
