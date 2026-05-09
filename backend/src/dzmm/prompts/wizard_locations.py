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
    return [
        Message(role="system", content=_SYSTEM),
        Message(
            role="user",
            content=f"类型：{genre}\n\n世界简介：\n{world_brief_md}\n\n请生成地点网络 JSON 数组。",
        ),
    ]
