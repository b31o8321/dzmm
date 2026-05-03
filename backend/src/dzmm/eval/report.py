from datetime import datetime, UTC
from dzmm.eval.judge_agent import EvalScore


def _avg(scores: list[EvalScore], attr: str) -> float:
    if not scores:
        return 0.0
    return sum(getattr(s, attr) for s in scores) / len(scores)


def generate_report(
    scores_a: list[EvalScore],
    config_a_name: str,
    scores_b: list[EvalScore],
    config_b_name: str,
) -> str:
    now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")

    def _table_row(name: str, scores: list[EvalScore]) -> str:
        if not scores:
            return f"| {name} | N/A | N/A | N/A | N/A | N/A |"
        return (
            f"| {name} "
            f"| {_avg(scores, 'plot_speed'):.1f} "
            f"| {_avg(scores, 'rule_violations'):.1f} "
            f"| {_avg(scores, 'rp_immersion'):.1f} "
            f"| {_avg(scores, 'dice_accuracy'):.1f} "
            f"| {_avg(scores, 'overall'):.1f} |"
        )

    def _detail_rows(scores: list[EvalScore]) -> str:
        if not scores:
            return "（无评分记录）\n"
        rows = ["| 回合 | 剧情推进 | 规则违反 | RP沉浸感 | 骰子准确 | 综合 | 评语 |",
                "|------|----------|----------|----------|----------|------|------|"]
        for s in scores:
            rows.append(
                f"| {s.turn} | {s.plot_speed:.1f} | {s.rule_violations} "
                f"| {s.rp_immersion:.1f} | {s.dice_accuracy:.1f} "
                f"| {s.overall:.1f} | {s.reasoning[:40]} |"
            )
        return "\n".join(rows) + "\n"

    winner = "平局"
    if scores_a and scores_b:
        avg_a = _avg(scores_a, "overall")
        avg_b = _avg(scores_b, "overall")
        if avg_a > avg_b + 0.5:
            winner = f"✅ **{config_a_name}** 胜出（+{avg_a - avg_b:.1f}）"
        elif avg_b > avg_a + 0.5:
            winner = f"✅ **{config_b_name}** 胜出（+{avg_b - avg_a:.1f}）"
        else:
            winner = f"🤝 平局（差距 {abs(avg_a - avg_b):.1f}，不显著）"

    return f"""# TRPG GM 质量评测报告

生成时间：{now}

## 总结

{winner}

## 均值对比

| 配置 | 剧情推进 | 规则违反(↓) | RP沉浸感 | 骰子准确 | **综合** |
|------|----------|------------|----------|----------|---------|
{_table_row(config_a_name, scores_a)}
{_table_row(config_b_name, scores_b)}

## {config_a_name} 详细评分

{_detail_rows(scores_a)}

## {config_b_name} 详细评分

{_detail_rows(scores_b)}

---
*评分由 Judge Agent（LLM-as-Judge）自动生成，仅供参考。*
"""
