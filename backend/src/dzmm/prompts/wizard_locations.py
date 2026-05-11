# ============================================================
# 开放世界向导 - 地点网络生成（wizard_locations.py）
# ============================================================
# 【开放世界地图是什么？】
#   开放世界模式下，游戏世界有一张"地点网络图"：
#   - 每个地点有名称、描述、类型（城市/野外/地下城/地标）
#   - 地点之间有"连接"关系，定义了 PC 可以从哪里走到哪里
#     以及需要花多少时间（travel_turns）
#
#   这就像一张游戏地图，但用 JSON 表示，供后端追踪 PC 的位置
#   和计算事件触发条件。
#
# 【连接（connections）的设计】
#   连接有方向和距离：
#   - direction: north/south/east/west/up/down/portal（上下楼梯、传送门等）
#   - distance: 1=相邻，2=较近，3+=较远
#   - travel_turns: 旅行需要的回合数
#
#   连接**必须双向**（A→B 则 B→A），否则 PC 无法回来。
#
# 【输出 JSON 数组的原因】
#   后端用 JSON 初始化地点数据库表，生成地图可视化，
#   并在每回合检查 PC 的位置和可达地点。
# ============================================================
from __future__ import annotations
from dzmm.models.client import Message

_SYSTEM = """你是开放世界 TRPG 的地图设计师。根据世界设定，生成地点网络。

输出严格为 JSON 数组，不加 markdown 围栏，不加注释：
[
  {
    "name": "地点名称",
    "description_md": "2-4句简介",
    "location_type": "city|dungeon|wilderness|landmark",
    "connections": [
      {"target_name": "连接地点名", "direction": "north|south|east|west|up|down|portal", "distance": 1, "travel_turns": 1}
    ],
    "initial_state": "normal"
  }
]

要求：
- 生成 6-10 个地点
- 每个地点至少有 1 个连接
- 连接必须双向出现（A→B 则 B→A）
- distance: 1=相邻, 2=较近, 3+=较远
- 包含多种类型地点（城市/野外/地下城/地标）
"""


def build_locations_messages(genre: str, world_brief_md: str) -> list[Message]:
    # genre：故事类型（帮助生成符合风格的地点，如"恐怖"类型会生成废弃医院、地下室等）
    # world_brief_md：世界简介（确保地点名称和描述符合世界观）
    return [
        Message(role="system", content=_SYSTEM),
        Message(
            role="user",
            content=f"类型：{genre}\n\n世界简介：\n{world_brief_md}\n\n请生成地点网络 JSON 数组。",
        ),
    ]
