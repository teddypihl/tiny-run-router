# backend/routing.py
from dataclasses import dataclass
from typing import List, Optional, Dict, Tuple
import heapq

from .data import Graph, Edge


def edge_cost(edge: Edge) -> float:
    """
    Cost for scoring (not for shortest path). You can tune this.
    """
    base = edge.distance_m

    # prefer main roads slightly
    if edge.road_type == "main_road":
        base *= 0.9
    elif edge.road_type == "residential":
        base *= 1.0
    else:  # path
        base *= 1.05

    # elevation_gain_m is currently 0, but this is ready for real data
    base += 3.0 * max(edge.elevation_gain_m, 0.0)
    return base


@dataclass
class RouteResult:
    nodes: List[str]
    distance_m: float
    elevation_gain_m: float
    score: float  # effective score including distance penalty


def _dijkstra(
    graph: Graph,
    start: str,
    max_dist: float,
    edge_penalty: Dict[Tuple[str, str], float] | None = None,
) -> Tuple[Dict[str, float], Dict[str, Optional[str]]]:
    """
    Standard Dijkstra on edge.distance_m, with optional penalties on edges.
    Returns:
      dist[node] = distance from start
      prev[node] = previous node on best path
    """
    if edge_penalty is None:
        edge_penalty = {}

    adjacency = graph.adjacency
    dist: Dict[str, float] = {start: 0.0}
    prev: Dict[str, Optional[str]] = {start: None}

    heap: List[Tuple[float, str]] = [(0.0, start)]

    while heap:
        d, u = heapq.heappop(heap)
        if d > dist.get(u, float("inf")):
            continue
        if d > max_dist:
            # no need to go farther: all future paths will be longer
            continue

        for e in adjacency.get(u, []):
            v = e.v
            base_w = e.distance_m
            if base_w <= 0:
                continue

            key = tuple(sorted((e.u, e.v)))
            penalty_factor = edge_penalty.get(key, 1.0)
            w = base_w * penalty_factor

            nd = d + w
            if nd < dist.get(v, float("inf")) and nd <= max_dist:
                dist[v] = nd
                prev[v] = u
                heapq.heappush(heap, (nd, v))

    return dist, prev


def _reconstruct_path(prev: Dict[str, Optional[str]], target: str) -> Optional[List[str]]:
    if target not in prev:
        return None
    path: List[str] = []
    cur: Optional[str] = target
    while cur is not None:
        path.append(cur)
        cur = prev.get(cur)
    path.reverse()
    return path


def _path_distance_and_elevation(graph: Graph, nodes: List[str]) -> Tuple[float, float, float]:
    """
    Returns (total_distance_m, total_elev_gain_m, total_cost_for_scoring)
    """
    if len(nodes) < 2:
        return 0.0, 0.0, 0.0

    total_dist = 0.0
    total_elev = 0.0
    total_cost = 0.0

    adjacency = graph.adjacency
    for u, v in zip(nodes[:-1], nodes[1:]):
        # find the edge u->v
        edge = None
        for e in adjacency.get(u, []):
            if e.v == v:
                edge = e
                break
        if edge is None:
            # should not happen if graph is consistent
            continue
        total_dist += edge.distance_m
        total_elev += max(edge.elevation_gain_m, 0.0)
        total_cost += edge_cost(edge)

    return total_dist, total_elev, total_cost


def find_best_loop(
    graph: Graph,
    start: str,
    d_min_m: float,
    d_max_m: float,
    elev_limit_m: float,
    target_m: float,
) -> Optional[RouteResult]:
    """
    Loop finder:

    1. Run Dijkstra from `start` to get distances to all nodes.
    2. Pick "far" nodes as candidate turnaround points.
    3. For each candidate v:
       - shortest path start->v
       - shortest path v->start, but heavily penalize re-using edges from the first half
    4. Combine to a loop and score by:
       - closeness to target_m
       - low elevation gain
       - low amount of repeated edges
    """

    if start not in graph.nodes:
        raise ValueError(f"Start node {start!r} not in graph")

    # 1) Forward Dijkstra: distances from start
    dist_fw, prev_fw = _dijkstra(graph, start, max_dist=d_max_m)

    # select candidate mid-points that are "far enough" but not insane
    candidates: List[Tuple[float, str]] = []
    for node_id, d in dist_fw.items():
        if d_min_m * 0.4 <= d <= target_m:  # tweakable range
            candidates.append((d, node_id))

    if not candidates:
        return None

    # sort so we try farther nodes first
    candidates.sort(reverse=True)

    best: Optional[RouteResult] = None

    # limit how many midpoints we test to keep it fast
    MAX_CANDIDATES = 40
    candidates = candidates[:MAX_CANDIDATES]

    for dist_to_v, v in candidates:
        # 2) reconstruct start -> v
        path_fw = _reconstruct_path(prev_fw, v)
        if not path_fw or len(path_fw) < 2:
            continue


        # build set of edges used in forward path (undirected)
        used_edges: Dict[Tuple[str, str], int] = {}
        for u, w in zip(path_fw[:-1], path_fw[1:]):
            key = tuple(sorted((u, w)))
            used_edges[key] = used_edges.get(key, 0) + 1

        # penalty: heavily discourage re-using same edges on the way back
        edge_penalty: Dict[Tuple[str, str], float] = {
            key: 4.0 for key in used_edges.keys()
        }

        remaining_dist_budget = d_max_m - dist_to_v
        if remaining_dist_budget <= 0:
            continue

        # 3) Dijkstra from v back towards start, with penalties
        dist_back, prev_back = _dijkstra(
            graph,
            start=v,
            max_dist=remaining_dist_budget,
            edge_penalty=edge_penalty,
        )

        if start not in dist_back:
            # no path back within remaining distance
            continue

        path_back = _reconstruct_path(prev_back, start)
        if not path_back or len(path_back) < 2:
            continue

        # combine paths into loop: start -> v -> ... -> start
        # path_fw: [start, ..., v]
        # path_back: [v, ..., start]
        loop_nodes = path_fw + path_back[1:]  # avoid duplicating v

        total_dist, total_elev, total_cost = _path_distance_and_elevation(
            graph, loop_nodes
        )

        if total_dist < d_min_m or total_dist > d_max_m:
            continue
        if total_elev > elev_limit_m:
            continue

        # measure how many edges were reused
        reuse_count = 0
        seen_edges = set()
        for u, w in zip(loop_nodes[:-1], loop_nodes[1:]):
            key = tuple(sorted((u, w)))
            if key in seen_edges:
                reuse_count += 1
            else:
                seen_edges.add(key)

        # score: closeness to target + penalty for re-use
        deviation = abs(total_dist - target_m)
        score = total_cost + 5.0 * (deviation ** 2) + 300.0 * reuse_count

        if best is None or score < best.score:
            best = RouteResult(
                nodes=loop_nodes,
                distance_m=total_dist,
                elevation_gain_m=total_elev,
                score=score,
            )

    return best
