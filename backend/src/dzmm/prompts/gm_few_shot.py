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

# ============================================================
# Few-shot 示例（Few-shot Example）
# ============================================================
# 【什么是 few-shot？】
#   Few-shot 是提示词工程的核心技术之一。
#   "zero-shot" = 只给指令，不给例子，让 LLM 自己猜格式；
#   "few-shot" = 给指令 + 几个具体例子（示范），让 LLM 照着格式输出。
#
#   例如，如果你只说"给我一首诗"（zero-shot），LLM 可能输出各种格式。
#   如果你先给一首示范诗，再说"按这个格式写一首"（few-shot），
#   输出会更稳定、更符合预期。
#
# 【为什么 TRPG 需要 few-shot？】
#   GM 的输出格式很复杂——需要同时输出多种 XML 标签（<narrative>、<dice>、
#   <npc_update> 等），并保持正确的顺序和内容结构。
#   不给例子，LLM 很容易格式漂移（随便发明新标签、顺序乱、属性写错）。
#   有了正例 + 反例，LLM 就有了"对照样本"，格式遵从率大幅提升。
#
# 【为什么要有反面示范（错误示范）？】
#   光说"禁止做 X"不如"这样做是错的，因为 Y"更有效。
#   LLM 看到反面例子后会强化对规则的理解，比单纯的文字描述更直观。
#
# 【为什么单独放在这个文件里？】
#   原来是内嵌在 gm_template.py 里的。那个文件有 542 行，其中约 80 行
#   是这段示例，代码难以阅读。提取出来后各文件职责清晰。
#   但功能上它仍然是 gm_template.py 的一部分，由 build_gm_messages() 注入。
#
# 【{character_name} 占位符说明】
#   示例中用了 {character_name} 而不是写死一个名字（如"张三"），
#   因为不同游戏的 PC 名字不同。build_gm_messages() 会先用 .format()
#   把 {character_name} 替换成实际的角色名，再把整段文字注入 System Prompt。
#
# 【{{ }} 说明】
#   Python .format() 里，{{ 是转义的 {，格式化后变成字面的 {。
#   所以示例里的 {{"name": "年轻卫兵", ...}} 在 .format() 后变成
#   {"name": "年轻卫兵", ...}，也就是普通的 JSON 对象字符串。
#
# 【v0.2.1 长上下文崩溃修复】
#   之前示例里有 "# 关键信息推进示范" 这样的 markdown 标题行。
#   在游戏进行到第 70+ 回合（上下文很长）时，LLM 会把这些标题
#   当作自己应该输出的格式，在正式叙事里也写出 "# 关键信息推进示范"。
#   修复：把所有标题改成 "--- xxx ---" 分隔线，LLM 就不会照抄了。
# ============================================================

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

--- 示范3：场地与NPC在场管理 ---

玩家「走出茶馆回到街道上」，正确输出：

<narrative>茶馆门吱呀一声推开，夜风裹着炭火气息扑来，街道上人影稀落。</narrative>

<pc_action>{character_name}踏出门槛，回头最后看了一眼店主。</pc_action>

<npc_update>
{{"name": "店主陈伯", "location": ""}}
</npc_update>

<location_enter name="九龙黑街" description="昏黄路灯把积水染成琥珀色，远处传来麻将碰撞声"/>

<choices>
- 沿街向北，往那道暗灯走去
- 停在门口，等一等再走
- 压低帽檐穿过人群
</choices>

说明：location="" 表示陈伯留在茶馆，不再出现在「九龙黑街」的在场NPC列表。物品同理用 `<location_item action="add|remove"/>`。

--- 示范4：dice 检定的密度峰值（潜行成功示范）---

玩家行动「悄悄绕到守卫背后，去偷桌上的钥匙」

正确输出：

<narrative>李少卿沿着墙根挪到值班室门口。</narrative>

<dice category="stealth" outcome="success" dc="12" pc_roll="15" mod="+2">
<scene>
门轴几乎没出声。屋里只有一盏油灯，摇曳的光把守卫的影子投在墙上像个昏睡的巨人。
李少卿屏住呼吸，三步、两步——指尖触到铜制的钥匙串。冰凉。
桌角的茶杯冒着热气，那个守卫前一秒还在抿酒。
</scene>
<reaction speaker="守卫张三" mood="无察觉">
（在椅子上轻微动了一下，喉咙里发出含糊的呓语）「……再来……一壶……」
</reaction>
</dice>

<narrative>钥匙到手。李少卿沿原路退出，把门带上半寸。</narrative>

<choices>
- 立即去打开囚室
- 先把钥匙复制一份，万一被人发现
- 顺手翻一下桌上的文件
</choices>

--- 反面示范（绝对不要这样输出） ---

<narrative>你成功潜行到守卫背后偷到了钥匙。</narrative>
<dice category="stealth" outcome="success" dc="12" pc_roll="15">潜行检定成功</dice>
<choices>...</choices>

注意：dice 内没有详细的感官 scene 和 NPC reaction = 错过了让玩家「看到」和「听到」的
机会，回合质感骤降。dice 是叙事密度的峰值——普通 narrative 可以白描快推进，dice 必须慢镜头。

--- 示范5：场所切换必须立即登记 ---

玩家行动：「推门进酒馆找老学者」

正确输出：

<narrative>林默推开吱呀作响的木门，潮湿的酒气和劣质烟草味迎面扑来。
老学者坐在角落，桌上一壶残酒，正用指节敲着杯沿，似乎在等什么人。</narrative>

<location_enter name="街尾酒馆" description="灯光昏黄的小酒馆，三五桌客人，老学者占着角落"/>

<say speaker="老学者">「来了？坐。我有些事得先告诉你。」</say>

<choices>
- 坐下听老学者要说什么
- 先点一壶酒
- 环视一下其他桌客人
</choices>

--- 反面示范（绝对不要这样输出） ---

<narrative>林默推开酒馆的门走了进去。老学者坐在角落。</narrative>
<say speaker="老学者">「来了？坐。」</say>
<choices>...</choices>

注意：narrative 已经描写 PC 进入了新地点（街尾酒馆），但**没 emit `<location_enter>`**
→ 玩家面板的「当前场所」还停在上个回合的街道，与剧情不一致。空间切换必须立即登记。

/* 以上仅为示例。实际输出必须从 <narrative> 开头，不要包含
「输出范例」「示范」「错误示范」这类元文字，也不要把示例里的
人名（陈子轩 / 老学者 / 年轻卫兵）抄到无关场景。 */
"""
