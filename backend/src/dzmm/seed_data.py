"""Default seed data for first-run setup.

Called from build_default_app() after init_db(). Idempotent — only inserts
when the corresponding table is empty.
"""
import json
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

from dzmm.db.models import ModelConfig, Screenplay, World

log = logging.getLogger(__name__)

_WORLDS = [
    {
        "name": "零区禁令：新京都 2091",
        "style": "dark",
        "rules_json": json.dumps({"mode": "standard"}),
        "content_md": (
            "# 2091 年的新京都\n\n"
            "三次「神经风暴」事件之后，政府在旧京都废墟上建了这座城——"
            "所有居民在出生时被植入合规芯片，每次越轨都会在档案里留下一个红点。"
            "五个红点，进零区。没人知道零区在哪，但每个人都知道进去就没有出来过。\n\n"
            "表面上，新京都是东亚最安全的城市：犯罪率 0.003%，自杀率不计入官方统计。\n\n"
            "## 势力\n"
            "- **公安脑控局（NCB）**：持有所有居民的神经档案，一念之间可以让人感到恐惧或欣快。\n"
            "- **地下频道「虫洞」**：在老城区下水道运营的匿名信息网，只能用改造过的聋哑型义体接入。\n"
            "- **「三月花」帮**：表面是花道馆，实际收容想摘除合规芯片的人，价格是你的一段记忆。\n"
            "- **芯片黑市**：二手芯片可以借用死人身份，但芯片残留的情绪会在夜里透出来。\n\n"
            "## 禁忌\n"
            "- 讨论合规芯片的工作原理：第一次警告，第二次红点。\n"
            "- 收藏 2068 年「神经风暴」之前的书籍或影像：算煽动罪，三个红点。\n"
            "- 与零区出来的人接触：理论上不存在，实际上 NCB 会在两周内登门。\n\n"
            "## 此刻\n"
            "你站在御苑线地铁站月台上。刚才检票口的闸机扫了你的芯片，"
            "屏幕显示了四个红点。你盯着那数字，一秒，两秒——你只记得三件出格的事。"
        ),
    },
    {
        "name": "上海·谍影 1937",
        "style": "dark",
        "rules_json": json.dumps({"mode": "standard"}),
        "content_md": (
            "# 民国二十六年，上海租界\n\n"
            "淞沪会战已经打响，但在法租界和英租界的分界线里，"
            "舞厅还亮着灯，赌场还开着门，五国情报机构在同一栋楼里租了不同的房间。\n\n"
            "信任是这座城最贵的东西，也是最容易伪造的东西。\n\n"
            "## 势力\n"
            "- **军统上海站**：戴笠直辖，行事凶狠，对叛徒向来是先杀后报。\n"
            "- **日本特务机关（土肥原系）**：在四马路开了家古董行做掩护，主要收买文人和商贾。\n"
            "- **中共上海地下党**：暗线极深，连军统内部都渗透了几个，谁也不知道是哪几个。\n"
            "- **英国 MI6 亚洲站**：只关心商业利益，但偶尔会用「利益交换」做些见不得人的事。\n"
            "- **白俄流亡圈**：散落在霞飞路的流亡贵族，没有祖国，但什么都愿意卖。\n\n"
            "## 规则\n"
            "- 身份是命。一套身份证件在黑市值半年口粮。\n"
            "- 任何人都可能是线人。同一桌吃饭的人里，平均有一个在给别人写报告。\n"
            "- 租界警察只管租界里的案子。出了租界边界，什么规矩都没有。\n\n"
            "## 此刻\n"
            "你在霞飞路一间茶馆的角落桌坐着，等一个上午十点要来的人。\n"
            "现在是十点零八分。对方给过你的接头暗号是：把茶壶盖翻过来放。\n"
            "隔壁桌的男人已经看了你三次了。"
        ),
    },
    {
        "name": "残光庇护所",
        "style": "horror",
        "rules_json": json.dumps({"mode": "standard"}),
        "content_md": (
            "# 核冬天，第七年\n\n"
            "核爆之后的第三年，太阳被遮蔽，粮食减产了九成。"
            "庇护所「残光」容纳了 800 人，现在还剩 340 人，还在以每月约十人的速度递减。\n\n"
            "没有人知道外面是否还有别的幸存者，通讯台的信号三年前就断了——\n"
            "或者说，三年前收到了最后一条信号，是一段乱码，没有人解出来过。\n\n"
            "## 派系\n"
            "- **管理委员会**：五人组成，掌控物资分配和「出局」决议。三个月选一次，上次投票有两张票是空白的。\n"
            "- **技师组**：掌管发电机和净水系统，是所里唯一无法被开除的人，因此也最傲慢。\n"
            "- **沉默者**：一批拒绝参与集体决策的人，聚在 B 区角落，据说晚上能听到他们在唱什么。\n"
            "- **外出小队**：每月出去一次搜刮补给，回来的人里会少一两个，原因各不相同。\n\n"
            "## 此刻的危机\n"
            "- 主食储量还剩 61 天。\n"
            "- 上周外出小队带回来了一个陌生人，他说外面还有一个比残光大三倍的庇护所，但拒绝说在哪。\n"
            "- 三天前发电机室发生了一次「意外」，一个技师死了。管委会说是事故，技师组说有人动过保险丝。\n\n"
            "## 此刻\n"
            "你在 C 区走廊，空气里有一股加热过的罐头味和霉味混在一起。\n"
            "走廊尽头那个房间的灯今天又开着——那是那个陌生人住的房间，管委会说他被单独关押了。\n"
            "门缝里透出来的不是电灯光，是烛火。庇护所里三年前就没有蜡烛了。"
        ),
    },
    {
        "name": "刀锋录·断江湖",
        "style": "dark",
        "rules_json": json.dumps({"mode": "standard"}),
        "content_md": (
            "# 武林乱世\n\n"
            "二十年前，「天机楼」以一份名单终结了一代江湖：名单上的人，"
            "要么死了，要么从此隐匿，要么成了天机楼的刀。"
            "名单叫《断江录》，一共一百三十二人，没有人知道入选的标准。\n\n"
            "你的师父在名单上。他死之前把一样东西交给了你，说：「不到绝境不能用。」\n\n"
            "## 势力\n"
            "- **天机楼**：没有楼主，只有「执事」，以黑衣白巾为记，出手不留生口。\n"
            "  据说它的金主是朝廷里某个王爷，但没有活着查清楚的人。\n"
            "- **残余江湖**：《断江录》没杀完的人，各自为战，彼此猜疑，以为对方是天机楼的细作。\n"
            "- **漕帮**：控制大运河沿线的货运和消息，中立原则，但价钱给够什么都做。\n"
            "- **忘川堂**：专门收留《断江录》上逃出来的人，代价是为忘川堂做三件事，不问内容。\n\n"
            "## 此刻\n"
            "你在扬州城外的破庙里醒来。身旁是一具尸体——"
            "你认识这个人，他是师父旧识，两天前刚托人给你传信说有要事相告。\n"
            "他后背有一道刀伤，伤口干净利落，是天机楼的手法。\n"
            "他的右手握着什么——是一截染血的黑色衣带，和一张折叠的纸。"
        ),
    },
]

_SCREENPLAYS = [
    {
        "world_index": 0,  # 零区禁令：新京都 2091
        "title": "合规人生的边界",
        "genre": "政治阴谋",
        "pc_name": "楚晓",
        "pc_profile_md": """## 楚晓

**身份：** NCB（神经合规局）前三级审核员，编号 C-0471

**背景：** 曾执行过 247 次"强制重置"申请审核，其中 3 次签发了自己后来质疑的处决令。六周前，她在常规清仓时发现档案库 B-7 里存在一个从未被分配合规芯片的区域——这在法律上不应该存在。

**特质：** 习惯在说谎前用右手拇指摩擦无名指指节；对纸质文件有近乎执念的偏好；从不相信巧合。

**携带：** 一枚已停用的四级权限芯片（失效日期：三周前）、审核官证（仍然有效）、记录着某个孤儿院地址的小纸条。""",
        "pc_base_stats_json": '{"调查":8,"交涉":6,"渗透":5,"战斗":3,"技术":6,"意志":7}',
    },
    {
        "world_index": 1,  # 上海·谍影 1937
        "title": "失联的猎雀人",
        "genre": "悬疑探案",
        "pc_name": "顾之行",
        "pc_profile_md": """## 顾之行

**身份：** 军统上海站外勤情报员，代号"鸢尾"

**背景：** 加入军统前是租界里的跑单帮，见过太多人为了活命出卖同伴。三年前被老站长亲自招募，执行过四次渗透任务，全身而退。两周前，联络人"麻雀"在例行接头后失踪，顾之行奉命查清原委——但他隐约察觉这次任务与组织内部的某条黑线有关。

**特质：** 能在三分钟内判断出一个陌生人的大概出身；喝茶从不加糖；在确认安全之前从不走同一条路两次。

**携带：** 军统证件（伪造身份：实业公司职员）、一把改装过消音弹的小型手枪、"麻雀"最后一封密信（部分字迹被水浸湿）。""",
        "pc_base_stats_json": '{"侦察":8,"潜伏":7,"格斗":6,"交际":5,"应变":7,"意志":6}',
    },
    {
        "world_index": 2,  # 残光庇护所
        "title": "核冬之后，第七十二天",
        "genre": "灾难求生",
        "pc_name": "沈语",
        "pc_profile_md": """## 沈语

**身份：** 庇护所三区医疗官，前传染病研究员

**背景：** 核冬来临前三天，她正在隔离舱内研究一种尚未命名的病毒变体，因此意外成了庇护所里唯一知道外面情况全貌的人——或者说，曾经知道。笔记本在第十二天的骚乱中遗失了。现在她靠残缺的记忆管理着日益枯竭的药品库，以及日益绝望的人心。

**特质：** 拥有过目不忘的短期记忆，但长期记忆在压力下会出现空白；习惯在诊断时做"没有用处的详细记录"；对谎言的厌恶近乎生理反应。

**携带：** 医疗急救箱（储量：约40%）、弄丢了一半内容的研究日志、三区配给钥匙卡、一支用完了子弹的注射型镇静枪。""",
        "pc_base_stats_json": '{"医疗":9,"科学":7,"交涉":5,"应变":6,"体能":4,"意志":8}',
    },
    {
        "world_index": 3,  # 刀锋录·断江湖
        "title": "封印的木匣",
        "genre": "政治阴谋",
        "pc_name": "裴无弦",
        "pc_profile_md": """## 裴无弦

**身份：** 独臂散修，前天机楼"弦"字级密探

**背景：** 天机楼共有七个字级密探，代号取自琴弦。"无弦"意味着他是第八个——从未被正式承认存在的那个。三年前，他奉命护送一个装有天机楼核心密档的木匣前往西疆，却在半路遭遇追杀，失去左臂，木匣却奇异地封印在他身上。自那以后，每当木匣感知到天机楼的气息，封印便会灼烧他的肌肤。

**特质：** 以残臂为荣，拒绝一切义肢；推算人心如推演棋局；对天机楼的人既防备又难以割舍。

**携带：** 封于右臂皮肤之下的神秘木匣（无法取出）、一把只有三尺长的断剑、天机楼通缉令（画像失真，但悬赏真实）。""",
        "pc_base_stats_json": '{"轻功":7,"剑术":8,"推算":9,"隐匿":6,"交锋":5,"内力":7}',
    },
]

_MODEL_CONFIGS = [
    {
        "name": "本地 qwen2.5:7b",
        "type": "ollama",
        "base_url": "http://localhost:11434",
        "model_name": "qwen2.5:7b",
        "timeout": 60.0,
    },
]


async def seed_if_empty(session_maker: async_sessionmaker[AsyncSession]) -> None:
    """Insert default worlds/screenplays/model_configs if those tables are empty.
    Each table is checked independently so partial DBs (e.g. user kept worlds
    but lost model_configs) get filled in for the missing pieces only."""
    async with session_maker() as s:
        worlds_existing = (
            await s.execute(select(World.id).limit(1))
        ).scalar_one_or_none()
        screenplays_existing = (
            await s.execute(select(Screenplay.id).limit(1))
        ).scalar_one_or_none()
        models_existing = (
            await s.execute(select(ModelConfig.id).limit(1))
        ).scalar_one_or_none()

        added = 0

        if worlds_existing is None:
            world_objs = [World(**w) for w in _WORLDS]
            s.add_all(world_objs)
            await s.flush()  # populate IDs
            added += len(world_objs)
            log.info("seeded %d default worlds", len(world_objs))

            # Screenplays reference worlds by index — only seed them in the same
            # run where we created the worlds, so the world_index mapping is
            # meaningful. If the user already has worlds, we don't add screenplays.
            if screenplays_existing is None:
                sp_objs = [
                    Screenplay(
                        world_id=world_objs[sp["world_index"]].id,
                        session_id=None,
                        title=sp["title"],
                        genre=sp["genre"],
                        pc_name=sp["pc_name"],
                        pc_profile_md=sp["pc_profile_md"],
                        pc_base_stats_json=sp["pc_base_stats_json"],
                    )
                    for sp in _SCREENPLAYS
                ]
                s.add_all(sp_objs)
                await s.flush()
                added += len(sp_objs)
                log.info("seeded %d default screenplays", len(sp_objs))

        if models_existing is None:
            model_objs = [ModelConfig(**m) for m in _MODEL_CONFIGS]
            s.add_all(model_objs)
            added += len(model_objs)
            log.info("seeded %d default model configs", len(model_objs))

        if added > 0:
            await s.commit()
        else:
            log.info("default data already present, skipping seed")
