"""长跑内容质量指标：近4回合开头重复率 + 对白格式漂移率 + 重复段计数。

用法：python3 quality_metrics.py <run_id> [BASE]
对比基线（v1.9.0 修复前，qwen2.5:7b-32k 120回合）：
  近4回合开头重复 77/119；行内冒号对白漂移 63/120；60字完全重复段 80 处
"""
import json, sys, urllib.request
from collections import Counter

BASE = sys.argv[2] if len(sys.argv) > 2 else "http://127.0.0.1:8908/api/v2"
run_id = sys.argv[1]

with urllib.request.urlopen(f"{BASE}/runs/{run_id}", timeout=30) as r:
    run = json.loads(r.read().decode())

turns = [t for t in run.get("turns", []) if t.get("kind") == "turn"]
narratives = [t.get("narrative") or "" for t in turns]
n = len(narratives)

# 指标1：近4回合开头重复（前30字）
opening_repeat = 0
for i in range(n):
    window = [x[:30] for x in narratives[max(0, i - 4):i]]
    if narratives[i][:30] and narratives[i][:30] in window:
        opening_repeat += 1

# 指标2：对白格式漂移——NPC名开头但未按「」锚定的行（含直引号包裹漂移）
import re
drift = 0
drift_lines = []
for text in narratives:
    for line in text.split("\n"):
        line = line.strip()
        m = re.match(r"^[“\"」]?([^\n：:，。]{1,12})[：:][”\"「]?(.+)$", line)
        if m and not line.endswith("」") and not line.endswith("』"):
            drift += 1
            drift_lines.append(line[:40])

# 指标3：跨回合重复句（≥25字句子出现>1次的总冗余次数）
sent = Counter()
for text in narratives:
    for s in re.split(r"[。！？\n]", text):
        s = s.strip()
        if len(s) >= 25:
            sent[s] += 1
dup60 = sum(c - 1 for c in sent.values() if c > 1)

# 指标4：结尾钩子缺失率（简单启发：无「？」或建议性语句）
print(json.dumps({
    "turns": n,
    "opening_repeat_4w": f"{opening_repeat}/{max(0, n-1)}",
    "dialogue_drift_lines": drift,
    "drift_samples": drift_lines[:5],
    "dup60_extra": dup60,
}, ensure_ascii=False, indent=1))
