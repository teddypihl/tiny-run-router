// frontend/main.js
const API_BASE = "https://tiny-run-router.onrender.com";

let map;
let routeLayer = null;
let homeMarker = null;   // marker showing the current start point
let startLatLng = null;  // Leaflet LatLng of current start point
let originalLatLngs = null;  // for rubber-band drag


function initMap() {
  // samma center som "home" i data.py (default start)
  const homeLat = 60.45;
  const homeLon = 22.266;

  // IMPORTANT: enable editing on the map
  map = L.map("map", { editable: true }).setView([homeLat, homeLon], 14);

  L.tileLayer("https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png", {
    maxZoom: 19,
    attribution:
      '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors, ' +
      '&copy; <a href="https://carto.com/attributions">CARTO</a>',
  }).addTo(map);

  // initial start point = "home"
  startLatLng = L.latLng(homeLat, homeLon);
  homeMarker = L.marker(startLatLng)
    .addTo(map)
    .bindPopup("Start")
    .openPopup();

  // klick på kartan flyttar startpunkten
  map.on("click", (e) => {
    startLatLng = e.latlng;
    if (homeMarker) {
      homeMarker.setLatLng(e.latlng);
    } else {
      homeMarker = L.marker(e.latlng)
        .addTo(map)
        .bindPopup("Start");
    }
  });
// drawRoadNetwork(); // debug view off
}

function setupEditingEvents() {
  // When you start dragging a vertex, snapshot the original route shape
  map.on("editable:vertex:dragstart", (e) => {
    if (!routeLayer || e.layer !== routeLayer) return;
    // clone current latlngs so we can use them as baseline
    originalLatLngs = routeLayer.getLatLngs().map((ll) => ll.clone());
  });

  // While dragging: nearby points "follow" with falloff,
  // unless Shift/Alt is held → then only this vertex moves.
  map.on("editable:vertex:drag", (e) => {
    if (!routeLayer || e.layer !== routeLayer || !originalLatLngs) return;

    const domEvent = e.originalEvent || e.event;
    const singleOnly = domEvent && (domEvent.shiftKey || domEvent.altKey);

    // If Shift/Alt is held, let Leaflet.Editable move only this point,
    // and don't touch neighbors.
    if (singleOnly) {
      return;
    }

    const currentLatLngs = routeLayer.getLatLngs();
    if (!currentLatLngs.length) return;

    // Index of the dragged vertex
    const idx = e.vertex.getIndex();

    const dragged = currentLatLngs[idx];
    const originalDragged = originalLatLngs[idx];

    const dLat = dragged.lat - originalDragged.lat;
    const dLng = dragged.lng - originalDragged.lng;

    // Rough meters (works fine for this use)
    const approxMoveM =
      Math.sqrt(dLat * dLat + dLng * dLng) * 111320; // ~m per degree

    // Base neighbors + extra depending on drag distance
    const baseFollow = 12;                        // at least this many neighbors
    const extraFollow = Math.floor(approxMoveM / 30); // 1 extra per ~30 m
    const MAX_FOLLOW_LIMIT = Math.min(60, currentLatLngs.length - 1);

    const MAX_FOLLOW = Math.min(
      MAX_FOLLOW_LIMIT,
      baseFollow + extraFollow
    );

    for (let offset = 1; offset <= MAX_FOLLOW; offset++) {
      const leftIndex = idx - offset;
      const rightIndex = idx + offset;

      // exponential falloff: close neighbors follow a lot, far neighbors a bit
      const falloff = Math.exp(-offset / 5); // larger denominator => smoother

      if (leftIndex >= 0) {
        currentLatLngs[leftIndex].lat =
          originalLatLngs[leftIndex].lat + dLat * falloff;
        currentLatLngs[leftIndex].lng =
          originalLatLngs[leftIndex].lng + dLng * falloff;
      }

      if (rightIndex < currentLatLngs.length) {
        currentLatLngs[rightIndex].lat =
          originalLatLngs[rightIndex].lat + dLat * falloff;
        currentLatLngs[rightIndex].lng =
          originalLatLngs[rightIndex].lng + dLng * falloff;
      }
    }

    routeLayer.setLatLngs(currentLatLngs);
  });

  // after you finish dragging one vertex, snap the *whole* shape
  map.on("editable:vertex:dragend", () => {
    snapRouteToRoads();
  });

  // 2) Double-click a vertex → delete it and re-snap route
  map.on("editable:vertex:click", (e) => {
    const domEvent = e.originalEvent || e.event;
    if (!domEvent) return;

    // detail === 2 → double click
    if (domEvent.detail === 2) {
      // remove that vertex from the polyline
      if (e.vertex && typeof e.vertex.delete === "function") {
        e.vertex.delete();
      }
      // and then rebuild + snap the route based on remaining points
      snapRouteToRoads();
    }
  });
}



async function snapRouteToRoads() {
  if (!routeLayer) return;

  const statusEl = document.getElementById("status");
  const latlngs = routeLayer.getLatLngs();
  if (!latlngs || latlngs.length < 2) return;

  const points = latlngs.map((ll) => ({ lat: ll.lat, lon: ll.lng }));

  try {
    statusEl.textContent = "Snapping route to roads…";
    statusEl.className = "";

    const res = await fetch(`${API_BASE}/route/snap`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ points }),
    });

    if (!res.ok) {
      const text = await res.text();
      throw new Error(`Error ${res.status}: ${text}`);
    }

    const data = await res.json();
    const snappedLatLngs = data.points.map((p) => L.latLng(p.lat, p.lon));
    routeLayer.setLatLngs(snappedLatLngs);

    if (routeLayer.editor) {
    routeLayer.editor.reset();
  }

    statusEl.textContent = "Route snapped to roads.";
    statusEl.className = "success";
  } catch (err) {
    console.error(err);
    statusEl.textContent = "Snap failed (see console).";
    statusEl.className = "error";
  }
}



function drawRoadNetwork() {
  console.log("Fetching /graph…");

  fetch(`${API_BASE}/graph`)
    .then((res) => res.json())
    .then((segments) => {
      console.log("Got segments from /graph:", segments.length);

      segments.forEach((seg) => {
        let color;
        let weight;

        if (seg.road_type === "main_road") {
          color = "#ff0000"; // BRIGHT RED, impossible to miss
          weight = 6;
        } else if (seg.road_type === "residential") {
          color = "#0000ff"; // BRIGHT BLUE
          weight = 4;
        } else {
          color = "#00ff00"; // NEON GREEN for paths
          weight = 3;
        }

        L.polyline(
          [
            [seg.lat1, seg.lon1],
            [seg.lat2, seg.lon2],
          ],
          {
            color,
            weight,
            opacity: 1.0,
            interactive: false,
          }
        ).addTo(map);
      });
    })
    .catch((err) => {
      console.error("Failed to load graph edges", err);
    });
}

async function fetchRoute(minKm, maxKm, maxElev) {
  const params = new URLSearchParams({
    distance_min_km: String(minKm),
    distance_max_km: String(maxKm),
    max_elevation_m: String(maxElev),
    start_node_id: "home", // används som default på backend
  });

  // om användaren klickat någonstans, skicka koordinaterna
  if (startLatLng) {
    params.set("start_lat", String(startLatLng.lat));
    params.set("start_lon", String(startLatLng.lng));
  }

  const url = `${API_BASE}/route?` + params.toString();
  const res = await fetch(url);

  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Error ${res.status}: ${text}`);
  }

  return res.json();
}

function drawRoute(route) {
  // ta bort gammal route
  if (routeLayer) {
    // disable editing on old layer (if any)
    if (routeLayer.editor) {
      routeLayer.disableEdit();
    }
    map.removeLayer(routeLayer);
  }

  const latlngs = route.coordinates.map((c) => [c.lat, c.lon]);

  routeLayer = L.polyline(latlngs, {
    weight: 5,
    color: "#007aff",   // iOS blue
    opacity: 0.9,
    lineJoin: "round",
    lineCap: "round",
  }).addTo(map);

  map.fitBounds(routeLayer.getBounds(), { padding: [40, 40] });
}

// Enable editing (drag vertices) for the current route
function enableRouteEditing() {
  const statusEl = document.getElementById("status");

  if (!routeLayer) {
    statusEl.textContent = "No route to edit yet.";
    statusEl.className = "error";
    return;
  }

  // Leaflet.Editable hook
  routeLayer.enableEdit(map);
  statusEl.textContent = "Edit mode: drag to bend. Hold Shift to move one node. Double-click a node to delete.";
  statusEl.className = "";
}

// Send edited route to backend and update distance
async function applyRouteEdits() {
  const statusEl = document.getElementById("status");

  if (!routeLayer) {
    statusEl.textContent = "No route to apply edits on.";
    statusEl.className = "error";
    return;
  }

  await snapRouteToRoads();


  const latlngs = routeLayer.getLatLngs();
  if (!latlngs || latlngs.length < 2) {
    statusEl.textContent = "Edited route is too short.";
    statusEl.className = "error";
    return;
  }

  const points = latlngs.map((ll) => ({
    lat: ll.lat,
    lon: ll.lng,
  }));

  try {
    statusEl.textContent = "Sending edited route…";
    const res = await fetch(`${API_BASE}/route/adjust`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ points }),
    });

    if (!res.ok) {
      const text = await res.text();
      throw new Error(`Error ${res.status}: ${text}`);
    }

    const data = await res.json();
    // Disable editing after apply (optional)
    if (routeLayer.editor) {
      routeLayer.disableEdit();
    }
    statusEl.textContent = `Edited loop: ${data.distance_km.toFixed(2)} km`;
    statusEl.className = "success";
  } catch (err) {
    console.error(err);
    statusEl.textContent = "Error applying edits (see console).";
    statusEl.className = "error";
  }
}

function setupForm() {
  const form = document.getElementById("route-form");
  const statusEl = document.getElementById("status");

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const min = parseFloat(document.getElementById("min-distance").value);
    const max = parseFloat(document.getElementById("max-distance").value);
    const maxElev = parseFloat(document.getElementById("max-elev").value);

    statusEl.textContent = "Searching...";
    statusEl.className = "";
    try {
      const route = await fetchRoute(min, max, maxElev);
      drawRoute(route);
      statusEl.textContent = `Found loop: ${route.distance_km.toFixed(
        2
      )} km, climb ${route.elevation_gain_m.toFixed(0)} m`;
      statusEl.className = "success";
    } catch (err) {
      console.error(err);
      statusEl.textContent = "No loop found or error (see console).";
      statusEl.className = "error";
    }
  });

  // Hook up edit buttons
  const editBtn = document.getElementById("edit-route-btn");
  const applyBtn = document.getElementById("apply-edits-btn");

  editBtn.addEventListener("click", enableRouteEditing);
  applyBtn.addEventListener("click", applyRouteEdits);
}

document.addEventListener("DOMContentLoaded", () => {
  initMap();
  setupEditingEvents();  // <--- add this
  setupForm();
});
