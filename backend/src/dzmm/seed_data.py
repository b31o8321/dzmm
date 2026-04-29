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
    "Riku": "riku.svg",
    "御坂雪": "yuki.svg",
    "佐藤亚矢": "aya.svg",
    "沈三川": "sanchuan.svg",
}

_WORLDS = [
    {
        "name": "赛博朋克 2087 香港",
        "style": "dark",
        "rules_json": json.dumps({"mode": "light"}),
        "content_md": (
            "# 2087 年的香港\n\n"
            "重力管理事故让维多利亚港半数高楼倾斜了 8 度，企业用悬空走廊把它们重新串成一座叠层之城。"
            "霓虹永不熄灭，雨水里溶着金属粉尘。\n\n"
            "## 势力\n"
            "- **同源株式会社**：垄断义体替换市场，给员工换义体作为续约「奖励」。\n"
            "- **九龙黑街**：地下医生、武器贩子、信息掮客的根据地，霓虹下的灰色地带。\n"
            "- **NetTribe**：信息自由派黑客组织，在内网里散播匿名信，被追到现实身份就会被抹除。\n\n"
            "## 禁忌\n"
            "- 持有未注册的脑机接口在街上被警察抓到，最低 5 年劳役。\n"
            "- 「记忆备份」服务受同源株式会社专控，第三方备份持有者会被认为是窃取知识产权。\n\n"
            "## 此刻\n"
            "你在九龙城寨边缘的一间小酒馆「霓虹猫」，外头雨很大，雨声被一根接漏的塑料管引到水桶里，"
            "节奏很奇怪——像是在打摩斯电码。"
        ),
    },
    {
        "name": "大正怪谈：东京 1923",
        "style": "horror",
        "rules_json": json.dumps({"mode": "light"}),
        "content_md": (
            "# 大正十二年的东京\n\n"
            "关东大地震三个月后，残垣断壁间冒出许多原本不存在的小路。"
            "走错一条，回头就找不到自己刚刚来时的方向。报社开始收到自称从「另一个东京」寄来的信。\n\n"
            "## 设定\n"
            "- 这是个**克苏鲁式怪谈**世界：异常存在但不显形，谁试图理解都会付出代价。\n"
            "- 警察对超常事件保持沉默，民间组织「灯笼会」秘密调查。\n"
            "- 现代科技刚刚萌芽：电话、留声机、汽车都是稀罕物，更显诡异。\n\n"
            "## 禁忌\n"
            "- 入夜后不要回头——走在你身后的可能不是你的同伴了。\n"
            "- 镜子蒙白布是常识。新搬入的房子要找阴阳师开光。\n\n"
            "## 此刻\n"
            "你站在浅草六区一家小关东煮店里。老板娘说，今晚客人比往常少，"
            "因为「街角那盏灯笼，从昨夜起就再没灭过」。"
        ),
    },
    {
        "name": "当代灵能事件簿",
        "style": "realistic",
        "rules_json": json.dumps({"mode": "light"}),
        "content_md": (
            "# 现代日本，平凡职场\n\n"
            "你在一家普通的中型公司做行政，加班、便利店饭团、末班电车，跟所有人一样。\n\n"
            "但三周前的一个雨夜，你在地铁车厢看到一个跟你穿着完全相同的女人，"
            "她隔着车窗对你比了个嘘的手势，下一站消失了。\n\n"
            "从那以后，你能模糊地「听见」物体的来历——一支别人借你的笔，一把你从没见过的伞。\n\n"
            "## 设定\n"
            "- 这是个**当代轻奇幻**世界：异能存在但极少，没有人公开承认。\n"
            "- 已知的异能者会用各种方式标记彼此（领带的特定纹样、咖啡店的暗语）。\n"
            "- 异能本身不暴力，但触碰太多会损伤理智。\n\n"
            "## 此刻\n"
            "现在是周三晚上 9 点，你刚加完班走出公司大楼，想去便利店买点吃的。"
            "便利店店员今天换了一个新人，胸前的工牌别得很紧，看起来很怕被你看到。"
        ),
    },
    {
        "name": "九州·青云志",
        "style": "realistic",
        "rules_json": json.dumps({"mode": "light"}),
        "content_md": (
            "# 九州·青云志\n\n"
            "九州大陆灵气浓郁，凡人寿不过百，修士御风而行，三千年间分化出五大正道宗门、"
            "七十二魔教余孽、与无数散修。三百年前一场「天劫之乱」让灵脉断裂，"
            "如今修真界进入「灵气稀薄期」——筑基愈发困难，金丹之上几成绝响。\n\n"
            "## 五大正道\n"
            "- **青云宗**：剑修为主，山门在云梦泽北，掌门席位空悬已久。\n"
            "- **天音寺**：佛门修法，讲究因果与心境，最忌「业火」。\n"
            "- **焚香谷**：丹道与符箓双修，弟子常下山行走江湖。\n"
            "- **合欢派**：双修旁门，被三派排挤但势力盘根错节。\n"
            "- **鬼王宗**：被列为魔教之首，三百年来与正道明争暗斗。\n\n"
            "## 修真境界\n"
            "炼气（一至九层） → 筑基 → 金丹 → 元婴 → 化神 → 渡劫 → 飞升。\n"
            "炼气期凡人身躯仍受寒暑生死所限；筑基后寿元三百，可御物飞行；金丹寿元八百。\n\n"
            "## 此刻\n"
            "你下山三月，于云梦泽边一处茶寮歇脚。雨刚停，泥路上一队商旅匆匆走过，"
            "马车上盖着的青布被风吹起一角，露出里面绑着的一个少女——她抬头看见了你。"
        ),
    },
]

_CHARACTERS = [
    {
        "world_idx": 0,
        "name": "Riku",
        "profile_md": (
            "## 基本信息\n"
            "- 性别：男 / 年龄：32 / 职业：自由黑客（前同源株式会社合同员工）\n"
            "- 外貌：左眼是改装过的扫描镜（瞳孔会泛紫），常年穿黑色连帽风衣\n\n"
            "## 性格\n"
            "谨慎多疑，但对认定的伙伴极度忠诚。会先观察十分钟再行动。\n\n"
            "## 背景\n"
            "三年前因为一次未经授权的内网访问被同源开除，公司没收了他原配的高级义体，"
            "现在用的左眼是从九龙黑街黑医那拿到的便宜替代品。\n\n"
            "## 弱点\n"
            "- 怕高（义体调试期摔过一次）\n"
            "- 听见母语方言（东北话）会下意识警觉"
        ),
        "base_stats_json": json.dumps({"hp": 22, "sanity": 14, "stamina": 12}),
    },
    {
        "world_idx": 1,
        "name": "御坂雪",
        "profile_md": (
            "## 基本信息\n"
            "- 性别：女 / 年龄：21 / 职业：早稻田大学文学部学生\n"
            "- 外貌：及肩黑发，不戴妆，常穿藏青色矢绞袴\n\n"
            "## 性格\n"
            "外表温吞、内心顽固。对未知事物先是好奇而不是恐惧——这正是危险所在。\n\n"
            "## 背景\n"
            "祖母是名古屋一带的口寄巫女。雪从小能看见别人看不见的「东西」，"
            "但被教育「不要回应、不要描述」。这次进京求学是她第一次离开家。\n\n"
            "## 物品\n"
            "- 祖母给的护身符（写着「念彼观音力」）\n"
            "- 一支自来水钢笔，蓝墨"
        ),
        "base_stats_json": json.dumps({"hp": 14, "sanity": 18, "stamina": 10}),
    },
    {
        "world_idx": 2,
        "name": "佐藤亚矢",
        "profile_md": (
            "## 基本信息\n"
            "- 性别：女 / 年龄：26 / 职业：中型贸易公司行政\n"
            "- 外貌：黑色短发，平时无妆，穿廉价但整齐的通勤套装\n\n"
            "## 性格\n"
            "怕麻烦，更怕引起别人注意。但被逼急了会做出让自己都意外的决定。\n\n"
            "## 背景\n"
            "三周前在末班电车上看到「另一个自己」之后开始拥有微弱的异能：\n"
            "触碰物体能模糊听到它的「来历」（前任主人的情绪、最近发生的事）。\n"
            "异能不可控，强烈的物体会让她头痛和耳鸣。\n\n"
            "## 物品\n"
            "- 公司工牌（已经习惯性把它别在内侧）\n"
            "- 一个旧手机壳，奶奶留下的（戴着会感到平静）"
        ),
        "base_stats_json": json.dumps({"hp": 16, "sanity": 16, "stamina": 11}),
    },
    {
        "world_idx": 3,
        "name": "沈三川",
        "profile_md": (
            "## 基本信息\n"
            "- 性别：男 / 年龄：22 / 身份：青云宗外门弟子，剑修一脉\n"
            "- 外貌：粗布青衫，腰悬一柄无名长剑，剑鞘磨损严重；左手虎口有旧疤\n\n"
            "## 修为\n"
            "炼气七层。在外门同辈里中上之姿，但筑基瓶颈卡了两年。\n"
            "携带一枚「凝灵丹」（拍卖会上花光积蓄买的，关键时刻能续命）。\n\n"
            "## 性格\n"
            "看似散漫不羁，实则锱铢必较。师门规矩懒得守，但欠人情必还。\n"
            "下山三月是为完成「历练任务」——证明能独立处理江湖事，回宗门换筑基资源。\n\n"
            "## 剑法\n"
            "学的是青云宗入门「青锋十三式」，未得真传。但他自己琢磨出一套不入流的「拖刀斩」，"
            "讲究先示弱后反击，正派同门很瞧不上。\n\n"
            "## 弱点\n"
            "- 灵气稀薄期下御剑飞行最多两个时辰\n"
            "- 见到「合欢派」装束的女子会下意识警惕（曾被骗过一次）\n"
            "- 不擅长跟正经修士周旋，更愿意混在江湖凡人里"
        ),
        "base_stats_json": json.dumps({"hp": 24, "sanity": 14, "stamina": 16, "灵力": 35}),
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
