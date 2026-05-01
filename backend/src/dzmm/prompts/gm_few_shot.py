"""GM few-shot example block.

Extracted from gm_template.py (v0.1.6 refactor) for readability — `gm_template.py`
was 542 lines, ~80 of which is this concrete正/反例 example. Output of
`build_gm_messages` must be character-for-character identical before/after this
extraction; `tests/test_gm_template.py` (37+ assertions on prompt content) is
the regression guard.

Contains the `{character_name}` placeholder which `build_gm_messages` substitutes
via `.format()` before splicing into the system message. Note: `{{` / `}}` are
escaped JSON braces (post-`.format()` they collapse to literal `{` / `}`).
"""

FEW_SHOT_EXAMPLE = """
# 输出范例（参考此格式，每个标签都必须闭合；narrative / pc_action / say 按发生顺序混合）

假设玩家行动是「上前盘问那个卫兵」，PC 名为「{character_name}」。正确的输出应当大致如下：

<narrative>
夜风带着潮气从巷口灌进来，把廊下那盏老式钠灯吹得忽明忽暗。空气里有淡淡的血腥气，混着卫兵制服上廉价烟草的味道。
</narrative>

<pc_action>{character_name}压低帽檐，三步并作两步走到那名年轻卫兵面前，目光落在他左手边的衣袖上。</pc_action>

<say speaker="年轻卫兵">「站——站住！这里禁止通行！」</say>

<narrative>
卫兵的右手紧紧攥住腰间电棍，指节泛白。他下意识地把左臂往身后藏，可那截深褐色血迹在惨白的灯光下分外刺眼。他大约二十出头，眉骨上一道新结的痂还没掉，眼神里慌乱多过敌意。
</narrative>

<say speaker="年轻卫兵">「你——你别过来。再往前我真的要叫人了。」</say>

<dice skill="洞察" target="12">
d20=15，成功
</dice>

<npc_update>
{{"name": "年轻卫兵", "favor_delta": 0, "emotion": {{"fear": +15}}, "state": "强装镇定，随时可能崩溃", "description": "二十出头的男性，制服左袖沾着新鲜血迹，明显在隐瞒什么", "purpose": "守住后门，但更想掩盖左袖的血迹"}}
</npc_update>

<hidden_event subject="年轻卫兵" kind="injury" severity="2"
              description="左臂有未处理的刀伤，正在缓慢渗血"
              consequence="2 回合内若不被揭穿/处理，他将因失血加剧而瘫坐，言语含糊"/>

<state_change>
{{"sanity": -1}}
</state_change>

<choices>
- 直接质问血迹的来历
- 假装没看见，套近乎打听通行
- 后退半步，观察周围有没有同伴
</choices>

# 关键信息推进示范（PC 问，NPC 当回合给）

假设玩家行动：「问老学者，那位接触者叫什么名字？在哪能找到？」

正确的输出：

<narrative>
老学者沉吟片刻，似乎在权衡。茶烟在他眼前盘旋一圈，他放下杯子。
</narrative>

<say speaker="老学者">「他叫陈子轩。常在九龙黑街第三巷的『清风茶寮』后院和人下棋。
你说是我介绍的，他大概会见你——但记得，他认实物不认人，带点能换的东西去。」</say>

<pc_action>{character_name}默默把这两个名字记在心里：陈子轩、清风茶寮。</pc_action>

<plot_event type="hook_introduced" importance="2">
线人陈子轩在九龙黑街清风茶寮后院，需要带交换物。
</plot_event>

<choices>
- 立即动身去清风茶寮
- 先回到客栈准备一些能交换的东西
- 多问老学者一些关于陈子轩的背景
</choices>

# 错误示范（绝对不要这样输出）

<narrative>
老学者眼神闪烁。
</narrative>

<say speaker="老学者">「我有一个接触者。但我们需要先确保信息可靠性。」</say>

<choices>
- 请问这位接触者的身份和联系方式？
- 您能告诉我更多信息吗？
- 我能怎么帮您？
</choices>

错误原因：PC 问了具体问题（接触者是谁、在哪），但 NPC 没给名字也没给地点，
choices 还在让 PC 重复同样的问题。这是被禁止的拖延循环。
"""
