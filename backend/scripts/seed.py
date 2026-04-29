"""Seed the dzmm DB with starter worlds, characters, and an Ollama model config.

Run while the backend is running (or start it first). Idempotent-ish: it just
appends entries; safe to run multiple times if you want copies.

Usage:
    .venv/bin/python scripts/seed.py
"""
import asyncio
import json

import httpx

BASE = "http://127.0.0.1:8765"

WORLDS = [
    {
        "name": "赛博朋克 2087 香港",
        "style": "dark",
        "rules_mode": "light",
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
        "rules_mode": "light",
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
        "rules_mode": "light",
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
]

CHARACTERS = [
    {
        # for 赛博朋克
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
        # for 大正怪谈
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
        # for 当代灵能
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
]

MODEL_CONFIGS = [
    {
        "name": "本地 qwen2.5:7b",
        "type": "ollama",
        "base_url": "http://localhost:11434",
        "model_name": "qwen2.5:7b",
        "timeout": 60.0,
    },
]


async def main():
    async with httpx.AsyncClient(base_url=BASE, timeout=10.0) as c:
        # ping first
        try:
            r = await c.get("/health")
            r.raise_for_status()
        except Exception:
            print(f"❌ backend not reachable at {BASE} — start it first:")
            print("   .venv/bin/python scripts/run_dev.py")
            return

        # Worlds
        world_ids: list[int] = []
        for w in WORLDS:
            r = await c.post("/worlds", json=w)
            r.raise_for_status()
            world_ids.append(r.json()["id"])
            print(f"✓ world: {w['name']} (id={r.json()['id']})")

        # Characters (link to world by index)
        for ch in CHARACTERS:
            payload = {
                "world_id": world_ids[ch["world_idx"]],
                "name": ch["name"],
                "profile_md": ch["profile_md"],
                "base_stats_json": ch["base_stats_json"],
            }
            r = await c.post("/characters", json=payload)
            r.raise_for_status()
            print(f"✓ character: {ch['name']} → world {world_ids[ch['world_idx']]} (id={r.json()['id']})")

        # Model configs
        for m in MODEL_CONFIGS:
            r = await c.post("/model_configs", json=m)
            r.raise_for_status()
            print(f"✓ model: {m['name']} (id={r.json()['id']})")

        print("\nseed complete. Open http://localhost:5173 and click '跑团' → '+ 新开一局'.")


if __name__ == "__main__":
    asyncio.run(main())
