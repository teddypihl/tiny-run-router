# backend/main.py
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from .edit import router as edit_router  

from typing import List, Tuple, Optional
import math


from .data import build_default_graph, build_graph, find_nearest_node_id
from .routing import find_best_loop


graph_center_lat = 60.4500
graph_center_lon = 22.2660
graph = build_default_graph()

app = FastAPI(
    title="Tiny Run Router",
    description="Tiny routing/path algorithm with constraints.",
    version="0.1.0",
)
app.include_router(edit_router)  # <--- add this


# CORS – tillåt frontend på localhost (just nu: allt, enkelt)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # byt till specifika origins senare
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class Coordinate(BaseModel):
    lat: float
    lon: float
    name: str


class RouteResponse(BaseModel):
    distance_km: float
    elevation_gain_m: float
    node_ids: List[str]
    coordinates: List[Coordinate]


@app.get("/route", response_model=RouteResponse)
def get_route(
    distance_min_km: float = Query(7.0, ge=0.1),
    distance_max_km: float = Query(9.0, ge=0.1),
    max_elevation_m: float = Query(150.0, ge=0.0),
    start_node_id: str = Query("home"),
    start_lat: float | None = Query(None),
    start_lon: float | None = Query(None),
):

    if distance_min_km > distance_max_km:
        raise HTTPException(status_code=400, detail="distance_min_km must be <= distance_max_km")

    d_min_m = distance_min_km * 1000
    d_max_m = distance_max_km * 1000

    # use midpoint as ideal distance
    target_m = 0.9 * d_max_m

    global graph, graph_center_lat, graph_center_lon

    # If user gave explicit coordinates and they are far from current graph center,
    # rebuild the graph around that pinned location.
    if start_lat is not None and start_lon is not None:
        d2 = (start_lat - graph_center_lat) ** 2 + (start_lon - graph_center_lon) ** 2
        # threshold ~0.03 degrees ≈ a few km
        if d2 > (0.03 ** 2):
            graph = build_graph(start_lat, start_lon, dist_m=2000)
            graph_center_lat = start_lat
            graph_center_lon = start_lon

        effective_start = find_nearest_node_id(graph, start_lat, start_lon)
    else:
        # no coordinates: just use the provided start_node_id in the current graph
        effective_start = start_node_id

    result = find_best_loop(
        graph=graph,
        start=effective_start,
        d_min_m=d_min_m,
        d_max_m=d_max_m,
        elev_limit_m=max_elevation_m,
        target_m=target_m,
    )


    if result is None:
        raise HTTPException(
            status_code=404,
            detail="No loop found up to the given max distance",
        )




    # NOTE: at the moment we *return* the best loop even if it's shorter
    # than distance_min_km – the client can decide how to use that info.



    coords: List[Coordinate] = []
    for node_id in result.nodes:
        node = graph.nodes[node_id]
        coords.append(Coordinate(lat=node.lat, lon=node.lon, name=node.name))

    return RouteResponse(
        distance_km=result.distance_m / 1000.0,
        elevation_gain_m=result.elevation_gain_m,
        node_ids=result.nodes,
        coordinates=coords,
    )
class GraphEdge(BaseModel):
    lat1: float
    lon1: float
    lat2: float
    lon2: float
    road_type: str

@app.get("/graph", response_model=List[GraphEdge])
def get_graph_edges():
    """
    Return all edges in the current graph as simple segments
    so the frontend can style them by road_type.
    """
    segments: List[GraphEdge] = []
    seen = set()  # to avoid duplicating undirected edges

    for u, edges in graph.adjacency.items():
        for e in edges:
            # undirected: (u,v) and (v,u) are the same, so we dedupe
            key = tuple(sorted((e.u, e.v)))
            if key in seen:
                continue
            seen.add(key)

            n1 = graph.nodes[e.u]
            n2 = graph.nodes[e.v]

            segments.append(
                GraphEdge(
                    lat1=n1.lat,
                    lon1=n1.lon,
                    lat2=n2.lat,
                    lon2=n2.lon,
                    road_type=e.road_type,
                )
            )

    return segments

class SnapPoint(BaseModel):
    lat: float
    lon: float


class SnapManyRequest(BaseModel):
    points: List[SnapPoint]


class SnapManyResponse(BaseModel):
    points: List[SnapPoint]




def _latlon_to_xy(lat: float, lon: float, lat0: float, lon0: float) -> Tuple[float, float]:
    """
    Very simple local projection: lat/lon -> x/y in meters around (lat0, lon0).
    Good enough at city scale.
    """
    # meters per degree
    k_lat = 111_320.0
    k_lon = 111_320.0 * math.cos(math.radians(lat0))

    x = (lon - lon0) * k_lon
    y = (lat - lat0) * k_lat
    return x, y


def _xy_to_latlon(x: float, y: float, lat0: float, lon0: float) -> Tuple[float, float]:
    k_lat = 111_320.0
    k_lon = 111_320.0 * math.cos(math.radians(lat0))

    lat = y / k_lat + lat0
    lon = x / k_lon + lon0
    return lat, lon


def _project_point_to_segment(
    px: float, py: float,
    x1: float, y1: float,
    x2: float, y2: float,
) -> Tuple[float, float, float]:
    """
    Project point P onto segment A(x1,y1)-B(x2,y2) in x/y meters.
    Returns (proj_x, proj_y, distance_m).
    """
    vx = x2 - x1
    vy = y2 - y1
    wx = px - x1
    wy = py - y1

    seg_len2 = vx * vx + vy * vy
    if seg_len2 == 0.0:
        # A and B are the same point
        return x1, y1, math.dist((px, py), (x1, y1))

    t = (vx * wx + vy * wy) / seg_len2
    t = max(0.0, min(1.0, t))  # clamp to segment

    proj_x = x1 + t * vx
    proj_y = y1 + t * vy

    dist = math.dist((px, py), (proj_x, proj_y))
    return proj_x, proj_y, dist


def _build_segments_for_snap():
    """
    Build a list of segments (lat1, lon1, lat2, lon2) from the current graph.
    Avoids double-counting undirected edges.
    """
    global graph
    segments: List[Tuple[float, float, float, float]] = []
    seen = set()

    for u, edges in graph.adjacency.items():
        for e in edges:
            key = tuple(sorted((e.u, e.v)))
            if key in seen:
                continue
            seen.add(key)

            n1 = graph.nodes[e.u]
            n2 = graph.nodes[e.v]
            segments.append((n1.lat, n1.lon, n2.lat, n2.lon))

    return segments


def _densify_points(points: List[SnapPoint], max_step_m: float = 25.0) -> List[SnapPoint]:
    """
    Insert extra points between the user’s edited points so snapping
    can follow corners instead of cutting across blocks.
    """
    global graph_center_lat, graph_center_lon

    if len(points) < 2:
        return points

    densified: List[SnapPoint] = []
    for i in range(len(points) - 1):
        p1 = points[i]
        p2 = points[i + 1]

        densified.append(p1)

        # work in local x/y meters
        x1, y1 = _latlon_to_xy(p1.lat, p1.lon, graph_center_lat, graph_center_lon)
        x2, y2 = _latlon_to_xy(p2.lat, p2.lon, graph_center_lat, graph_center_lon)
        dx = x2 - x1
        dy = y2 - y1
        seg_len = math.hypot(dx, dy)

        if seg_len > max_step_m:
            # how many interior points do we want?
            n = int(seg_len // max_step_m)
            for k in range(1, n + 1):
                t = k / (n + 1)
                xi = x1 + dx * t
                yi = y1 + dy * t
                lat_i, lon_i = _xy_to_latlon(xi, yi, graph_center_lat, graph_center_lon)
                densified.append(SnapPoint(lat=lat_i, lon=lon_i))

    densified.append(points[-1])
    return densified


@app.post("/route/snap", response_model=SnapManyResponse)
def snap_route(req: SnapManyRequest):
    """
    Geometric snapping:

    1. Densify the edited polyline (add points every ~25 m).
    2. For each point, project to nearest road segment in the graph.
    3. Keep the very first and very last coordinates exactly as user edited.
    """
    global graph, graph_center_lat, graph_center_lon

    if not graph.nodes:
        # fallback: nothing to do
        return SnapManyResponse(points=req.points)

    pts = req.points
    if len(pts) == 0:
        return SnapManyResponse(points=[])

    # 1) Densify polyline so corners follow streets instead of cutting through blocks
    dense_pts = _densify_points(pts, max_step_m=25.0)

    # 2) Build all OSM segments once
    segments = _build_segments_for_snap()
    if not segments:
        return SnapManyResponse(points=pts)

    snapped_dense: List[SnapPoint] = []
    MAX_SNAP_DIST_M = 60.0  # max distance to snap; further = leave as is

    for p in dense_pts:
        px, py = _latlon_to_xy(p.lat, p.lon, graph_center_lat, graph_center_lon)

        best_dist = float("inf")
        best_proj_xy: Optional[Tuple[float, float]] = None

        for (lat1, lon1, lat2, lon2) in segments:
            x1, y1 = _latlon_to_xy(lat1, lon1, graph_center_lat, graph_center_lon)
            x2, y2 = _latlon_to_xy(lat2, lon2, graph_center_lat, graph_center_lon)

            proj_x, proj_y, dist = _project_point_to_segment(px, py, x1, y1, x2, y2)

            if dist < best_dist:
                best_dist = dist
                best_proj_xy = (proj_x, proj_y)

        if best_proj_xy is None or best_dist > MAX_SNAP_DIST_M:
            # too far from any road → keep user point
            snapped_dense.append(SnapPoint(lat=p.lat, lon=p.lon))
        else:
            proj_lat, proj_lon = _xy_to_latlon(
                best_proj_xy[0], best_proj_xy[1],
                graph_center_lat, graph_center_lon,
            )
            snapped_dense.append(SnapPoint(lat=proj_lat, lon=proj_lon))

    # 3) Keep the exact start and end coordinates from the user
    if snapped_dense:
        snapped_dense[0] = SnapPoint(lat=pts[0].lat, lon=pts[0].lon)
        snapped_dense[-1] = SnapPoint(lat=pts[-1].lat, lon=pts[-1].lon)

    return SnapManyResponse(points=snapped_dense)

