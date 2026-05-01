"""GM few-shot example block.

Extracted from gm_template.py (v0.1.6 refactor) for readability — `gm_template.py`
was 542 lines, ~80 of which is this concrete正/反例 example. Output of
`build_gm_messages` must be character-for-character identical before/after this
extraction; `tests/test_gm_template.py` (37+ assertions on prompt content) is
the regression guard.

Contains the `{character_name}` placeholder which `build_gm_messages` substitutes
via `.format()` before splicing into the system message. Note: `{{` / `}}` are
escaped JSON braces (post-`.format()` they collapse to literal `{` / `}`).

v0.2.1 long-context fix: removed all `# heading` markdown lines from this block
and replaced them with `--- xxx ---` separators, and trimmed example bodies
~40%. Live play at turn 70+ saw the GM literally copying the markdown headings
(e.g. "# 关键信息推进示范") into its own output — a textbook long-context
collapse where the model treats few-shot scaffolding as part of its expected
response template. The trailing /* ... */ comment reinforces "do not copy
this meta text".
"""

FEW_SHOT_EXAMPLE = """
--- 输出范例（仅供参考标签格式，禁止抄写内容）---

玩家行动「盘问卫兵」，PC 名为「{character_name}」，正确输出大致是：

<narrative>夜风带着潮气灌进巷口，空气里有淡淡的血腥气。</narrative>

<pc_action>{character_name}压低帽檐走到卫兵面前，目光落在他左袖。</pc_action>

<say speaker="年轻卫兵">「站——站住！」</say>

<narrative>卫兵下意识把左臂往身后藏，那截深褐色血迹分外刺眼。</narrative>

<dice skill="洞察" target="12">d20=15，成功</dice>

<npc_update>
{{"name": "年轻卫兵", "emotion": {{"fear": +15}}, "state": "强装镇定"}}
</npc_update>

<hidden_event subject="年轻卫兵" kind="injury" severity="2"
              description="左臂渗血" consequence="2 回合内将瘫坐"/>

<state_change>{{"sanity": -1}}</state_change>

<choices>
- 直接质问血迹的来历
- 假装没看见，套近乎打听通行
- 后退半步，观察周围
</choices>

--- 示范2：关键信息推进（PC 问，NPC 当回合就给名字+地点）---

玩家「问老学者，那位接触者叫什么名字？」正确输出：

<say speaker="老学者">「他叫陈子轩。常在九龙黑街第三巷『清风茶寮』后院和人下棋。说是我介绍的，记得带能换的东西。」</say>

<pc_action>{character_name}把名字记下：陈子轩、清风茶寮。</pc_action>

<plot_event type="hook_introduced" importance="2">
线人陈子轩在九龙黑街清风茶寮后院，需带交换物。
</plot_event>

<choices>
- 立即动身去清风茶寮
- 先回客栈准备交换物
- 再多问老学者关于陈子轩的背景
</choices>

--- 错误示范（绝对不要这样输出）---

<say speaker="老学者">「我有个接触者，但需要先确保信息可靠性。」</say>
<choices>
- 请问这位接触者的身份和联系方式？
- 您能告诉我更多吗？
</choices>

错误原因：PC 已问具体问题（是谁、在哪），NPC 却没给名字也没给地点，choices 还在让 PC 重复同样的问题——被禁止的拖延循环。

--- 示范3：信息顺序（按故事时间线排列，say 紧跟引发它的动作）---

玩家「上前对店主搭话」正确输出（按发生顺序：场景 → PC 动作 → NPC 回应 → 余韵）：

<narrative>柜台后铜灯昏黄，店主低头数着银钱。</narrative>

<pc_action>{character_name}走到柜台前，轻敲了一下木面。</pc_action>

<say speaker="店主">「客官有何指教？」</say>

<narrative>店主抬眼，眉间一皱，铜灯映出他眼底的疲惫。</narrative>

错误顺序（绝对不要）：
<say speaker="店主">「客官有何指教？」</say>
<pc_action>{character_name}走到柜台前。</pc_action>
<narrative>店主抬眼。</narrative>
错误原因：把 say 放到了 pc_action 之前——NPC 在 PC 动作之前就开口，时序倒置。

/* 以上仅为示例。实际输出必须从 <narrative> 开头，不要包含
「输出范例」「示范」「错误示范」这类元文字，也不要把示例里的
人名（陈子轩 / 老学者 / 年轻卫兵）抄到无关场景。 */
"""
