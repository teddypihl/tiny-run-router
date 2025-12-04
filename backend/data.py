# backend/data.py
from dataclasses import dataclass
from typing import Dict, List

import osmnx as ox


@dataclass
class Node:
    id: str
    name: str
    lat: float
    lon: float
    elevation: float  # meters (we'll keep 0 for now)


@dataclass
class Edge:
    u: str
    v: str
    distance_m: float
    road_type: str       # "path", "residential", "main_road"
    elevation_gain_m: float  # positive if uphill u -> v


@dataclass
class Graph:
    nodes: Dict[str, Node]
    adjacency: Dict[str, List[Edge]]


def _classify_road_type(highway) -> str:
    """
    Map OSM 'highway' tag to our simple categories.
    """
    if isinstance(highway, list):
        highway = highway[0]

    if highway in {"motorway", "trunk", "primary"}:
        return "main_road"
    if highway in {
        "secondary",
        "tertiary",
        "unclassified",
        "residential",
        "living_street",
        "service",
    }:
        return "residential"
    # everything else we treat as "path" (footway, cycleway, track, steps...)
    return "path"


def _add_undirected_edge(
    adjacency: Dict[str, List[Edge]],
    u: str,
    v: str,
    distance_m: float,
    road_type: str,
    elev_u: float,
    elev_v: float,
) -> None:
    elev_gain_uv = max(elev_v - elev_u, 0.0)
    elev_gain_vu = max(elev_u - elev_v, 0.0)

    adjacency.setdefault(u, []).append(
        Edge(u=u, v=v, distance_m=distance_m,
             road_type=road_type, elevation_gain_m=elev_gain_uv)
    )
    adjacency.setdefault(v, []).append(
        Edge(u=v, v=u, distance_m=distance_m,
             road_type=road_type, elevation_gain_m=elev_gain_vu)
    )


# backend/data.py  (keep the dataclasses and helpers above as they are)

def build_graph(center_lat: float, center_lon: float, dist_m: int = 3000) -> Graph:
    """
    Build a graph from OpenStreetMap around a given center point.
    """
    G = ox.graph_from_point(
        (center_lat, center_lon),
        dist=dist_m,
        network_type="walk",
        simplify=True,
    )

    # make it undirected (we want to be able to run both directions)
    G = ox.convert.to_undirected(G)

    # pick the OSM node closest to the requested center
    start_osm_node = None
    best_d2 = float("inf")
    for osm_id, data in G.nodes(data=True):
        lat = float(data.get("y"))
        lon = float(data.get("x"))
        d2 = (lat - center_lat) ** 2 + (lon - center_lon) ** 2
        if d2 < best_d2:
            best_d2 = d2
            start_osm_node = osm_id

    if start_osm_node is None:
        raise RuntimeError("Could not find a start node in the OSM graph")

    nodes: Dict[str, Node] = {}
    adjacency: Dict[str, List[Edge]] = {}
    osm_to_id: Dict[int, str] = {}

    # create Node objects; rename the center one to "home"
    for idx, (osm_id, data) in enumerate(G.nodes(data=True)):
        if osm_id == start_osm_node:
            node_id = "home"
            name = "Home"
        else:
            node_id = f"n{idx}"
            name = f"Node {idx}"

        lat = float(data.get("y"))
        lon = float(data.get("x"))

        nodes[node_id] = Node(
            id=node_id,
            name=name,
            lat=lat,
            lon=lon,
            elevation=0.0,
        )
        osm_to_id[osm_id] = node_id

    # create Edge objects
    for u_osm, v_osm, edata in G.edges(data=True):
        u_id = osm_to_id[u_osm]
        v_id = osm_to_id[v_osm]

        length = float(edata.get("length", 0.0))
        if length <= 0:
            continue

        highway = edata.get("highway", "residential")
        road_type = _classify_road_type(highway)

        elev_u = nodes[u_id].elevation
        elev_v = nodes[v_id].elevation

        _add_undirected_edge(
            adjacency,
            u=u_id,
            v=v_id,
            distance_m=length,
            road_type=road_type,
            elev_u=elev_u,
            elev_v=elev_v,
        )

    print(
        f"Built graph with {len(nodes)} nodes and "
        f"{sum(len(v) for v in adjacency.values())} directed edges."
    )
    return Graph(nodes=nodes, adjacency=adjacency)


def build_default_graph() -> Graph:
    """
    Default graph around Turku (used at startup).
    """
    CENTER_LAT = 60.4500
    CENTER_LON = 22.2660
    return build_graph(CENTER_LAT, CENTER_LON)


def find_nearest_node_id(graph: Graph, lat: float, lon: float) -> str:
    """
    Find the node id in our Graph whose (lat, lon) is closest to the given point.
    """
    best_id = None
    best_d2 = float("inf")

    for node_id, node in graph.nodes.items():
        d2 = (node.lat - lat) ** 2 + (node.lon - lon) ** 2
        if d2 < best_d2:
            best_d2 = d2
            best_id = node_id

    if best_id is None:
        raise RuntimeError("No nodes in graph")
    return best_id

