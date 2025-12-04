# backend/edit.py
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List
import math

router = APIRouter()


class EditablePoint(BaseModel):
    lat: float
    lon: float


class EditableRouteRequest(BaseModel):
    points: List[EditablePoint]


class EditableRouteResponse(BaseModel):
    distance_km: float


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Great-circle distance between 2 lat/lon points in meters.
    Simple haversine; good enough for running routes.
    """
    R = 6371000.0  # Earth radius in meters

    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)

    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


@router.post("/route/adjust", response_model=EditableRouteResponse)
def adjust_route(payload: EditableRouteRequest):
    """
    Take an edited route polyline (list of lat/lon points),
    compute its length, and return updated stats.

    Later we could:
    - snap points to nearest graph nodes
    - re-evaluate elevation, etc.
    """
    pts = payload.points
    if len(pts) < 2:
        raise HTTPException(status_code=400, detail="Route must contain at least 2 points.")

    total_m = 0.0
    for p1, p2 in zip(pts[:-1], pts[1:]):
        total_m += _haversine_m(p1.lat, p1.lon, p2.lat, p2.lon)

    return EditableRouteResponse(distance_km=total_m / 1000.0)
