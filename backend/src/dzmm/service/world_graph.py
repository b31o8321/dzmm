# ============================================================
# world_graph.py — 世界地图的图结构工具
#
# 【这个模块解决什么问题？】
# 开放世界地图由若干「地点」（WorldLocation）组成，地点之间有道路相连。
# Director 需要知道「某个事件发生地距离玩家有多远」，才能决定
# 这个事件现在是否应该对玩家产生影响（还是只能作为遥远的传言）。
#
# 这个模块提供两个工具：
#   build_graph：把数据库里的地点列表转成「邻接表」图结构
#   bfs_distance：在图上用 BFS 计算两点之间的最短跳数
#
# 【BFS 宽度优先搜索是什么？为什么用它？】
# BFS（Breadth-First Search，宽度优先搜索）是一种图搜索算法。
# 它从起点出发，先访问所有距离为 1 的邻居，
# 再访问距离为 2 的邻居，依此类推——就像水波一圈圈向外扩散。
#
# 为什么用 BFS 而不是其他算法？
# 因为 BFS 在「无权图」（所有边权重相同）中能找到最短路径。
# 我们的世界地图里每条道路的「代价」相同（走一步就是一跳），
# 所以 BFS 是最简单、最合适的选择。
#
# 对比：
#   - DFS（深度优先）：不一定找最短路径，可能走很长的弯路
#   - Dijkstra：适合有权重的图（如道路有远近之分），这里没必要
#   - BFS：适合无权图，代码简单，总能找最短跳数
#
# 实际例子：
# 地图：城镇A ─ 森林B ─ 城堡C
#              └─ 洞穴D ─ 城堡C
# 从城镇A到城堡C的距离：
#   - 路径1：A → B → C = 2 跳
#   - 路径2：A → B → D → C = 3 跳
# BFS 会找到最短路径：2 跳
# ============================================================
"""Spatial graph utilities for WorldLocation topology.

build_graph(locations) → adjacency dict {loc_id: [neighbor_id, ...]}
bfs_distance(graph, src, dst) → int hop count (999 = unreachable)
"""
from __future__ import annotations

import json
from collections import deque  # 双端队列，BFS 的核心数据结构（高效的队列）


# ────────────────────────────────────────────────────────────
# 构建邻接表图结构
# ────────────────────────────────────────────────────────────

def build_graph(locations: list[dict]) -> dict[int, list[int]]:
    # 【邻接表是什么？】
    # 邻接表是表示图的一种方式，格式：{节点ID: [邻居ID列表]}
    # 例如：{1: [2, 3], 2: [1, 4], 3: [1], 4: [2]}
    # 表示：地点1连接着地点2和3，地点2连接着1和4，以此类推。
    #
    # 【为什么是无向图？】
    # 现实中的道路通常是双向的：能从A走到B，也能从B走回A。
    # 所以每条连接边都被添加两次（A→B 和 B→A），构成「无向图」。
    """Build adjacency list from a list of location dicts.

    Each dict must have keys: id (int), connections_json (str).
    connections_json is a list of {target_id, ...} objects.
    Graph is treated as undirected (edges added both ways).
    """
    graph: dict[int, list[int]] = {}  # 邻接表，键是地点 ID，值是邻居 ID 列表
    for loc in locations:
        loc_id = int(loc["id"])
        graph.setdefault(loc_id, [])  # 确保每个地点至少有一个（空的）邻居列表
        # connections_json 是存在数据库里的 JSON 字符串，需要解析
        # 格式例：[{"target_id": 2, "description": "北边的小路"}, ...]
        try:
            conns = json.loads(loc.get("connections_json") or "[]")
        except (TypeError, ValueError):
            conns = []  # JSON 解析失败就当没有连接
        for conn in conns:
            try:
                neighbor = int(conn["target_id"])  # 邻居地点的 ID
            except (KeyError, TypeError, ValueError):
                continue  # 格式不对就跳过这条连接
            graph.setdefault(neighbor, [])  # 确保邻居节点也在图里
            # 添加 loc_id → neighbor 的单向连接（如果还没有）
            if neighbor not in graph[loc_id]:
                graph[loc_id].append(neighbor)
            # 同时添加 neighbor → loc_id 的反向连接（无向图的关键）
            if loc_id not in graph[neighbor]:
                graph[neighbor].append(loc_id)
    return graph


# ────────────────────────────────────────────────────────────
# BFS 最短路径搜索
# ────────────────────────────────────────────────────────────

def bfs_distance(graph: dict[int, list[int]], src: int, dst: int) -> int:
    # 【BFS 工作原理的详细解释】
    # 1. 把起点 src 放入队列，距离为 0
    # 2. 从队列头部取出一个节点
    # 3. 查看这个节点的所有邻居：
    #    - 如果邻居是终点 dst → 找到了！返回当前距离 + 1
    #    - 如果邻居没访问过 → 加入队列，距离 + 1
    #    - 如果邻居已访问过 → 跳过（避免死循环）
    # 4. 重复步骤 2-3，直到队列为空（返回 999 表示不可达）
    #
    # 【deque（双端队列）的优势】
    # deque.popleft() 是 O(1) 操作，而 list.pop(0) 是 O(n) 操作。
    # 在 BFS 中频繁从队列头部取出元素，用 deque 更高效。
    """Return the shortest hop count from src to dst. Returns 999 if unreachable."""
    if src == dst:
        return 0  # 起点和终点相同，距离为 0

    visited = {src}  # 记录已访问的节点，防止重复访问（避免无限循环）
    # queue 存储 (当前节点ID, 到达该节点的距离) 元组
    queue: deque[tuple[int, int]] = deque([(src, 0)])

    while queue:
        node, dist = queue.popleft()  # 取出队列最前面的节点（FIFO 顺序）
        for neighbor in graph.get(node, []):  # 遍历当前节点的所有邻居
            if neighbor == dst:
                return dist + 1  # 找到终点，返回距离（当前距离 + 1 跳）
            if neighbor not in visited:
                visited.add(neighbor)             # 标记为已访问
                queue.append((neighbor, dist + 1))  # 加入队列，距离加 1

    # 队列耗尽还没找到终点 → 两点之间没有路径（不可达）
    # 返回 999 作为「无穷大」的代替（实际地图不会有这么远的路径）
    return 999
