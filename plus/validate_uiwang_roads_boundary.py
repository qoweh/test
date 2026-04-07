#!/usr/bin/env python3
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
PLUS = ROOT / "plus"

BOUNDARY_FILE = ROOT / "second report" / "gpt" / "this_uiwang_boundary.geojson"
ROADS_FILE = PLUS / "uiwang_osm_roads_filtered.geojson"

OUT_DETAIL_CSV = PLUS / "uiwang_road_boundary_validation.csv"
OUT_SUMMARY_CSV = PLUS / "uiwang_road_boundary_validation_summary.csv"
OUT_QUALITY_CSV = PLUS / "uiwang_road_quality_checks.csv"


def load_boundary_rings(path: Path):
    data = json.loads(path.read_text(encoding="utf-8"))
    rings = []

    for feature in data.get("features", []):
        geom = feature.get("geometry", {})
        gtype = geom.get("type")
        coords = geom.get("coordinates", [])

        if gtype == "Polygon":
            if coords:
                ring = coords[0]
                if ring and ring[0] != ring[-1]:
                    ring = ring + [ring[0]]
                rings.append(ring)
        elif gtype == "MultiPolygon":
            for poly in coords:
                if poly:
                    ring = poly[0]
                    if ring and ring[0] != ring[-1]:
                        ring = ring + [ring[0]]
                    rings.append(ring)

    if not rings:
        raise ValueError("No boundary ring found")

    return rings


def point_in_ring(lon: float, lat: float, ring):
    inside = False
    n = len(ring)
    if n < 3:
        return False

    j = n - 1
    for i in range(n):
        xi, yi = ring[i]
        xj, yj = ring[j]

        intersects = ((yi > lat) != (yj > lat)) and (
            lon < (xj - xi) * (lat - yi) / ((yj - yi) + 1e-15) + xi
        )
        if intersects:
            inside = not inside
        j = i

    return inside


def point_in_polygons(lon: float, lat: float, rings):
    for ring in rings:
        if point_in_ring(lon, lat, ring):
            return True
    return False


def orientation(a, b, c):
    v = (b[1] - a[1]) * (c[0] - b[0]) - (b[0] - a[0]) * (c[1] - b[1])
    if abs(v) < 1e-12:
        return 0
    return 1 if v > 0 else 2


def on_segment(a, b, c):
    return (
        min(a[0], c[0]) - 1e-12 <= b[0] <= max(a[0], c[0]) + 1e-12
        and min(a[1], c[1]) - 1e-12 <= b[1] <= max(a[1], c[1]) + 1e-12
    )


def segments_intersect(p1, p2, q1, q2):
    o1 = orientation(p1, p2, q1)
    o2 = orientation(p1, p2, q2)
    o3 = orientation(q1, q2, p1)
    o4 = orientation(q1, q2, p2)

    if o1 != o2 and o3 != o4:
        return True

    if o1 == 0 and on_segment(p1, q1, p2):
        return True
    if o2 == 0 and on_segment(p1, q2, p2):
        return True
    if o3 == 0 and on_segment(q1, p1, q2):
        return True
    if o4 == 0 and on_segment(q1, p2, q2):
        return True

    return False


def line_intersects_ring(coords, ring):
    if len(coords) < 2 or len(ring) < 2:
        return False

    for i in range(1, len(coords)):
        p1 = tuple(coords[i - 1])
        p2 = tuple(coords[i])
        for j in range(1, len(ring)):
            q1 = tuple(ring[j - 1])
            q2 = tuple(ring[j])
            if segments_intersect(p1, p2, q1, q2):
                return True
    return False


def line_intersects_boundary(coords, rings):
    for ring in rings:
        if line_intersects_ring(coords, ring):
            return True
    return False


def to_float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def main():
    rings = load_boundary_rings(BOUNDARY_FILE)
    roads = json.loads(ROADS_FILE.read_text(encoding="utf-8"))

    detail_rows = []
    way_ids = []

    for feature in roads.get("features", []):
        geom = feature.get("geometry", {})
        if geom.get("type") != "LineString":
            continue

        props = feature.get("properties", {})
        coords = geom.get("coordinates", [])
        way_id = str(props.get("way_id", "")).strip()
        name = (props.get("name") or "").strip()
        highway = (props.get("highway") or "").strip()
        length_m = to_float(props.get("length_m"))

        way_ids.append(way_id)

        vertex_count = len(coords)
        inside_count = 0
        invalid_coord_count = 0

        for c in coords:
            if len(c) < 2:
                invalid_coord_count += 1
                continue
            lon, lat = c[0], c[1]
            if not (-180.0 <= lon <= 180.0 and -90.0 <= lat <= 90.0):
                invalid_coord_count += 1
                continue
            if point_in_polygons(lon, lat, rings):
                inside_count += 1

        intersects = line_intersects_boundary(coords, rings)

        if invalid_coord_count > 0:
            status = "invalid_coordinates"
        elif vertex_count == 0:
            status = "empty_geometry"
        elif inside_count == vertex_count:
            status = "inside"
        elif inside_count > 0 or intersects:
            status = "crossing_boundary"
        else:
            status = "outside"

        detail_rows.append(
            {
                "way_id": way_id,
                "name": name,
                "highway": highway,
                "length_m": round(length_m, 2),
                "vertex_count": vertex_count,
                "inside_vertex_count": inside_count,
                "outside_vertex_count": max(vertex_count - inside_count, 0),
                "intersects_boundary": "yes" if intersects else "no",
                "invalid_coord_count": invalid_coord_count,
                "validation_status": status,
            }
        )

    detail_rows.sort(key=lambda r: (r["validation_status"], -(r["length_m"] or 0), r["way_id"]))

    with OUT_DETAIL_CSV.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "way_id",
                "name",
                "highway",
                "length_m",
                "vertex_count",
                "inside_vertex_count",
                "outside_vertex_count",
                "intersects_boundary",
                "invalid_coord_count",
                "validation_status",
            ],
        )
        writer.writeheader()
        writer.writerows(detail_rows)

    status_summary = defaultdict(lambda: {"segment_count": 0, "total_length_m": 0.0})
    for r in detail_rows:
        s = r["validation_status"]
        status_summary[s]["segment_count"] += 1
        status_summary[s]["total_length_m"] += to_float(r["length_m"])

    summary_rows = []
    for status, v in sorted(status_summary.items(), key=lambda kv: kv[0]):
        summary_rows.append(
            {
                "validation_status": status,
                "segment_count": v["segment_count"],
                "total_length_m": round(v["total_length_m"], 2),
                "total_length_km": round(v["total_length_m"] / 1000.0, 3),
            }
        )

    with OUT_SUMMARY_CSV.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["validation_status", "segment_count", "total_length_m", "total_length_km"],
        )
        writer.writeheader()
        writer.writerows(summary_rows)

    way_id_counts = Counter(way_ids)
    duplicate_way_ids = sum(1 for _, c in way_id_counts.items() if c > 1)
    missing_way_id = sum(1 for w in way_ids if not w)
    missing_highway = sum(1 for r in detail_rows if not r["highway"])
    non_positive_length = sum(1 for r in detail_rows if to_float(r["length_m"]) <= 0)

    quality_rows = [
        {"check_name": "total_segments", "value": len(detail_rows)},
        {"check_name": "duplicate_way_id_count", "value": duplicate_way_ids},
        {"check_name": "missing_way_id_count", "value": missing_way_id},
        {"check_name": "missing_highway_count", "value": missing_highway},
        {"check_name": "non_positive_length_count", "value": non_positive_length},
        {
            "check_name": "outside_status_count",
            "value": sum(1 for r in detail_rows if r["validation_status"] == "outside"),
        },
        {
            "check_name": "invalid_coordinates_status_count",
            "value": sum(1 for r in detail_rows if r["validation_status"] == "invalid_coordinates"),
        },
    ]

    with OUT_QUALITY_CSV.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["check_name", "value"])
        writer.writeheader()
        writer.writerows(quality_rows)

    print(json.dumps({"summary": summary_rows, "quality": quality_rows}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
