"""Default seed data for first-run setup.

Called from build_default_app() after init_db(). Idempotent — only inserts
when the corresponding table is empty.
"""
import json
import logging
import shutil
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

from dzmm.config import APP_DIR
from dzmm.db.models import Character, ModelConfig, World

log = logging.getLogger(__name__)

# Mapping from preset character name to its bundled portrait filename in
# repo_root/frontend/public/portraits/. Names match the entries in _CHARACTERS.
_PORTRAIT_FILES = {
    "楚晓": "riku.svg",
    "顾之行": "sanchuan.svg",
    "沈语": "aya.svg",
    "裴无弦": "sanchuan.svg",
}

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

_CHARACTERS = [
    {
        "world_idx": 0,
        "name": "楚晓",
        "profile_md": (
            "## 基本信息\n"
            "- 性别：女 / 年龄：29 / 职业：NCB 前数据审核员，现无业\n"
            "- 外貌：利落短发，惯用右手，右手腕有一道不够深的疤。穿廉价合规的灰色通勤装。\n\n"
            "## 性格\n"
            "习惯在脑子里把所有可能性排列一遍再开口。话少，但说出口的字没有废的。\n"
            "对「对的事」有一种固执的执念——哪怕她越来越不确定什么是「对」。\n\n"
            "## 背景\n"
            "她在 NCB 干了六年，审核市民的神经档案，给越轨行为打红点。\n"
            "三周前，她在档案里发现一个七岁女孩的账号已经有四个红点——\n"
            "查不到任何对应的越轨记录。她截了屏，那天晚上自己档案里多了一个红点。\n"
            "第二天她辞职了，现在还剩两次机会。\n\n"
            "## 能力与物品\n"
            "- 六年审核工作让她能快速判断谁在撒谎（DC -2）\n"
            "- 知道 NCB 内部的几个漏洞，但用一次少一次\n"
            "- 一个改装过的旧手表，能屏蔽芯片信号约十分钟，充电一次只能用两回\n\n"
            "## 弱点\n"
            "- 她的脸在 NCB 数据库里，被人脸识别扫到概率很高\n"
            "- 对「无辜者受害」有应激反应，容易冲动覆盖理性判断"
        ),
        "base_stats_json": json.dumps({"hp": 18, "sanity": 15, "stamina": 14}),
    },
    {
        "world_idx": 1,
        "name": "顾之行",
        "profile_md": (
            "## 基本信息\n"
            "- 性别：男 / 年龄：34 / 职业：军统上海站外勤，编号「鸽七」\n"
            "- 外貌：中等身材，脸不出众，正是这行最需要的样子。常穿长衫，随季节换色。\n\n"
            "## 性格\n"
            "情绪很少在脸上。不是冷漠，是经过训练的克制。\n"
            "他信任程序多于直觉——但有一种情况例外：当程序本身出了问题的时候。\n\n"
            "## 背景\n"
            "入行十一年，亲历三次叛变，从中学到一件事：\n"
            "叛变的人通常不是坏人，只是走到了某个没有退路的路口。\n"
            "他的上线三天前失联了。站长说等通知，但他在失联前最后一次通话里，\n"
            "只说了一句话：「名单是真的，但用法是假的。」\n\n"
            "## 能力与物品\n"
            "- 跟踪与反跟踪（城市环境中可降低被察觉概率）\n"
            "- 三套备用身份（洋行职员、报社记者、药材商），证件齐全\n"
            "- 一支德制袖珍手枪，六发子弹，备弹十二发\n"
            "- 上线给过他一串电话号码，说「只在活不下去的时候打」\n\n"
            "## 弱点\n"
            "- 酒是他的软肋，三杯之后判断力下降，话也开始多了\n"
            "- 对女性目标有一套固定的心理防线，但如果对方先说真话，他会手软"
        ),
        "base_stats_json": json.dumps({"hp": 20, "sanity": 14, "stamina": 16}),
    },
    {
        "world_idx": 2,
        "name": "沈语",
        "profile_md": (
            "## 基本信息\n"
            "- 性别：女 / 年龄：31 / 职业：前外出小队医疗员，现任庇护所诊室负责人\n"
            "- 外貌：手常年有碘伏的气味，左眼比右眼小，那是核冬天第一年一次意外留下的。\n\n"
            "## 性格\n"
            "对数字有病态的信任：粮食天数、温度、成功率——她把所有能量化的东西都量化。\n"
            "这帮助她在最坏的情况下保持清醒，也让她有时候忘记自己面对的是人而不是变量。\n\n"
            "## 背景\n"
            "她在外出小队待了三年，亲眼看着十七个人在任务里没有回来。\n"
            "第四年她拒绝继续外出，管委会让她留下来管诊室，但把她的口粮配额降了一档。\n"
            "现在那个陌生人住进来之后，他每天早上会来她的诊室，说头痛，\n"
            "但她检查不到任何生理原因——而且他的核辐射指数是她见过最低的，"
            "比庇护所里出生长大、从没出过门的孩子还低。\n\n"
            "## 能力与物品\n"
            "- 医疗判断（诊断、急救、调配药物储量）\n"
            "- 记忆力极好，庇护所 340 人她能叫出 310 个名字和过往病史\n"
            "- 一本手写的庇护所人员档案，比管委会的官方版本详细三倍\n\n"
            "## 弱点\n"
            "- 亲历太多死亡，她对新的感情投入有强烈的防御本能\n"
            "- 技师组的人不信任她，因为她三年前在报告里写了一份「燃料不足以支撑另一个冬天」的评估"
        ),
        "base_stats_json": json.dumps({"hp": 16, "sanity": 17, "stamina": 13}),
    },
    {
        "world_idx": 3,
        "name": "裴无弦",
        "profile_md": (
            "## 基本信息\n"
            "- 性别：男 / 年龄：27 / 身份：散修，曾是某门派弃徒\n"
            "- 外貌：左臂从肘以下是假肢——竹制，关节处缠着布，有焦痕。右手五指完好，持刀。\n\n"
            "## 武功\n"
            "擅轻功和暗器，近身刀法凌厉但走的是「伤敌一千自损八百」的路子。\n"
            "没有内功底子，靠硬功夫和快弥补。生死之间打过十一场，活下来了十一次，全带伤。\n\n"
            "## 性格\n"
            "言语刻薄，但从不对弱者动手。欠人情会还，被人害不会忘。\n"
            "他在意活下去，比在意任何立场或大义都多——这是他唯一的原则，也是最难动摇的。\n\n"
            "## 背景\n"
            "他的师父死在《断江录》之前，死于门派内部。\n"
            "师父死之前把一件东西交给他，说不到绝境不能用。他不知道那是什么，\n"
            "因为那东西被密封着，十三年了他没打开过——不是不想，是怕开了就再没退路。\n"
            "天机楼三天前联系了他，让他交出那件东西，说可以用一条活路换。\n\n"
            "## 物品\n"
            "- 腰间一个铜锁木匣，锁上有血封（强开会触发某种机关）\n"
            "- 二十枚淬了见血封喉的梅花镖，备用镖头六枚\n"
            "- 一张漕帮通行令，可以在运河沿线免检过关\n\n"
            "## 弱点\n"
            "- 假肢在雨天反应迟钝，近身格斗时是明显破绽\n"
            "- 他的脸被天机楼存了画影图形，大城市里行走需要易容"
        ),
        "base_stats_json": json.dumps({"hp": 22, "sanity": 13, "stamina": 18}),
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


def _copy_bundled_portraits(char_objs: list[Character]) -> None:
    """Copy bundled SVG portraits from frontend/public/portraits into
    APP_DIR/portraits and set portrait_path on the matching Character objects.
    Silently skips when source dir is missing (e.g. backend-only bundle)."""
    # backend/src/dzmm/seed_data.py → repo_root is parents[3]
    repo_root = Path(__file__).resolve().parents[3]
    portrait_src_dir = repo_root / "frontend" / "public" / "portraits"
    if not portrait_src_dir.is_dir():
        return
    portraits_dst_dir = APP_DIR / "portraits"
    portraits_dst_dir.mkdir(parents=True, exist_ok=True)
    for c in char_objs:
        src_filename = _PORTRAIT_FILES.get(c.name)
        if not src_filename:
            continue
        src = portrait_src_dir / src_filename
        if not src.exists():
            continue
        dst = portraits_dst_dir / f"{c.id}.svg"
        try:
            shutil.copy(src, dst)
            c.portrait_path = str(dst)
        except Exception:
            log.warning("failed to copy portrait for %s", c.name, exc_info=True)


async def seed_if_empty(session_maker: async_sessionmaker[AsyncSession]) -> None:
    """Insert default worlds/characters/model_configs if those tables are empty.
    Each table is checked independently so partial DBs (e.g. user kept worlds
    but lost model_configs) get filled in for the missing pieces only."""
    async with session_maker() as s:
        worlds_existing = (
            await s.execute(select(World.id).limit(1))
        ).scalar_one_or_none()
        chars_existing = (
            await s.execute(select(Character.id).limit(1))
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

            # Characters reference worlds by index — only seed them in the same
            # run where we created the worlds, so the world_idx mapping is
            # meaningful. If the user already has worlds, we don't add chars.
            if chars_existing is None:
                char_objs = [
                    Character(
                        world_id=world_objs[c["world_idx"]].id,
                        name=c["name"],
                        profile_md=c["profile_md"],
                        base_stats_json=c["base_stats_json"],
                    )
                    for c in _CHARACTERS
                ]
                s.add_all(char_objs)
                await s.flush()  # populate IDs so we can name portrait files by id
                _copy_bundled_portraits(char_objs)
                added += len(char_objs)
                log.info("seeded %d default characters", len(char_objs))

        if models_existing is None:
            model_objs = [ModelConfig(**m) for m in _MODEL_CONFIGS]
            s.add_all(model_objs)
            added += len(model_objs)
            log.info("seeded %d default model configs", len(model_objs))

        if added > 0:
            await s.commit()
        else:
            log.info("default data already present, skipping seed")
