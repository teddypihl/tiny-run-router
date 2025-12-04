# Tiny Run Router

Tiny Run Router is a small web app that generates running loops on real city streets, lets the user **edit the route directly on the map**, and then **re-snaps** the edited route back to the road network.

It consists of:

- A **Python / FastAPI backend** that:
  - Downloads a walkable street network from OpenStreetMap using `osmnx`
  - Builds an internal graph of nodes and edges
  - Finds “nice” loops using a custom routing algorithm
  - Exposes endpoints for:
    - Loop generation
    - Returning the road graph
    - Accepting edited routes and recalculating distance
    - Snapping edited routes back onto roads

- A **vanilla JS + Leaflet frontend** that:
  - Shows a sleek Apple-style map UI
  - Lets the user choose a start point by clicking on the map
  - Requests a loop from the backend with distance/elevation constraints
  - Draws the generated route as a polyline
  - Enables interactive editing:
    - Dragging the route
    - Rubber-banding nearby points to keep the shape smooth
    - Snapping edits back to roads via the backend

---

## Tech Stack

**Backend**

- Python
- FastAPI
- `osmnx` (for fetching + building the street graph from OpenStreetMap)
- Custom graph + routing logic (Dijkstra-based)

**Frontend**

- Static HTML/CSS/JS
- Leaflet (`leaflet.js`)
- `Leaflet.Editable` plugin for draggable polylines and vertices

---

## How It Works (High-Level)

### 1. Graph Building (`backend/data.py`)

At startup, the backend builds a graph around Turku:

- Uses `osmnx.graph_from_point((lat, lon), dist=..., network_type="walk")`
- Converts it to undirected (`ox.convert.to_undirected`)
- Wraps it in custom dataclasses:

```python
@dataclass
class Node:
    id: str
    name: str
    lat: float
    lon: float
    elevation: float  # currently 0, but code is ready for real elevation

@dataclass
class Edge:
    u: str
    v: str
    distance_m: float
    road_type: str       # "path", "residential", "main_road"
    elevation_gain_m: float

- How to run:
  - `python3 -m venv venv && source venv/bin/activate`
  - `pip install -r requirements.txt`
  - `uvicorn backend.main:app --reload`
  - `cd frontend && python -m http.server 5500`
