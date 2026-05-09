"""Spatial graph utilities for WorldLocation topology.

build_graph(locations) → adjacency dict {loc_id: [neighbor_id, ...]}
bfs_distance(graph, src, dst) → int hop count (999 = unreachable)
"""
from __future__ import annotations

import json
from collections import deque


def build_graph(locations: list[dict]) -> dict[int, list[int]]:
    """Build adjacency list from a list of location dicts.

    Each dict must have keys: id (int), connections_json (str).
    connections_json is a list of {target_id, ...} objects.
    Graph is treated as undirected (edges added both ways).
    """
    graph: dict[int, list[int]] = {}
    for loc in locations:
        loc_id = int(loc["id"])
        graph.setdefault(loc_id, [])
        try:
            conns = json.loads(loc.get("connections_json") or "[]")
        except (TypeError, ValueError):
            conns = []
        for conn in conns:
            try:
                neighbor = int(conn["target_id"])
            except (KeyError, TypeError, ValueError):
                continue
            graph.setdefault(neighbor, [])
            if neighbor not in graph[loc_id]:
                graph[loc_id].append(neighbor)
            if loc_id not in graph[neighbor]:
                graph[neighbor].append(loc_id)
    return graph


def bfs_distance(graph: dict[int, list[int]], src: int, dst: int) -> int:
    """Return the shortest hop count from src to dst. Returns 999 if unreachable."""
    if src == dst:
        return 0
    visited = {src}
    queue: deque[tuple[int, int]] = deque([(src, 0)])
    while queue:
        node, dist = queue.popleft()
        for neighbor in graph.get(node, []):
            if neighbor == dst:
                return dist + 1
            if neighbor not in visited:
                visited.add(neighbor)
                queue.append((neighbor, dist + 1))
    return 999
