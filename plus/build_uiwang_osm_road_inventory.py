#!/usr/bin/env python3
import csv
import json
import math
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
PLUS = ROOT / "plus"
RAW_ROADS = PLUS / "raw_api" / "osm_uiwang_bbox_highways.json"
BOUNDARY = ROOT / "second report" / "gpt" / "this_uiwang_boundary.geojson"

OUT_GEOJSON = PLUS / "uiwang_osm_roads_filtered.geojson"
OUT_SEGMENTS_CSV = PLUS / "uiwang_osm_roads_segments.csv"
OUT_TYPE_CSV = PLUS / "uiwang_osm_road_type_summary.csv"
OUT_NAME_CSV = PLUS / "uiwang_osm_named_roads_summary.csv"
OUT_STATS_JSON = PLUS / "uiwang_osm_stats.json"


def load_boundary_polygons(path: Path):
    data = json.loads(path.read_text(encoding="utf-8"))
    polygons = []

    for feature in data.get("features", []):
        geom = feature.get("geometry", {})
        gtype = geom.get("type")
        coords = geom.get("coordinates", [])

        if gtype == "Polygon":
            if coords:
                polygons.append(coords[0])
        elif gtype == "MultiPolygon":
            for poly in coords:
                if poly:
                    polygons.append(poly[0])

    if not polygons:
        raise ValueError("No polygon geometry found in boundary file")

    return polygons


def point_in_ring(lon: float, lat: float, ring):
    inside = False
    n = len(ring)
    if n < 3:
        return False

    j = n - 1
    for i in range(n):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]

        intersects = ((yi > lat) != (yj > lat)) and (
            lon < (xj - xi) * (lat - yi) / ((yj - yi) + 1e-15) + xi
        )
        if intersects:
            inside = not inside
        j = i

    return inside


def point_in_polygons(lon: float, lat: float, polygons):
    for ring in polygons:
        if point_in_ring(lon, lat, ring):
            return True
    return False


def haversine_m(lon1, lat1, lon2, lat2):
    r = 6371008.8
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)

    a = (
        math.sin(dphi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2.0) ** 2
    )
    return 2 * r * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def line_length_m(coords):
    if len(coords) < 2:
        return 0.0
    total = 0.0
    for i in range(1, len(coords)):
        lon1, lat1 = coords[i - 1]
        lon2, lat2 = coords[i]
        total += haversine_m(lon1, lat1, lon2, lat2)
    return total


def line_touches_city(geom, polygons):
    points = [(p["lon"], p["lat"]) for p in geom]
    if not points:
        return False

    for lon, lat in points:
        if point_in_polygons(lon, lat, polygons):
            return True

    # Fallback: check segment midpoints for boundary crossings.
    for i in range(1, len(points)):
        lon = (points[i - 1][0] + points[i][0]) / 2.0
        lat = (points[i - 1][1] + points[i][1]) / 2.0
        if point_in_polygons(lon, lat, polygons):
            return True

    return False


def main():
    polygons = load_boundary_polygons(BOUNDARY)

    raw = json.loads(RAW_ROADS.read_text(encoding="utf-8"))
    elements = raw.get("elements", [])

    filtered_features = []
    segments = []

    for way in elements:
        if way.get("type") != "way":
            continue

        geom = way.get("geometry", [])
        tags = way.get("tags", {})

        if not geom:
            continue
        if "highway" not in tags:
            continue
        if not line_touches_city(geom, polygons):
            continue

        coords = [[p["lon"], p["lat"]] for p in geom]
        length_m = line_length_m(coords)

        record = {
            "way_id": way.get("id"),
            "highway": tags.get("highway", ""),
            "name": tags.get("name", ""),
            "ref": tags.get("ref", ""),
            "lanes": tags.get("lanes", ""),
            "maxspeed": tags.get("maxspeed", ""),
            "oneway": tags.get("oneway", ""),
            "bridge": tags.get("bridge", ""),
            "tunnel": tags.get("tunnel", ""),
            "length_m": round(length_m, 2),
        }
        segments.append(record)

        filtered_features.append(
            {
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": coords},
                "properties": record,
            }
        )

    type_summary = defaultdict(lambda: {"segments": 0, "total_length_m": 0.0, "named_segments": 0})
    name_summary = defaultdict(lambda: {"segments": 0, "total_length_m": 0.0, "highway": ""})

    for s in segments:
        h = s["highway"] or "unknown"
        type_summary[h]["segments"] += 1
        type_summary[h]["total_length_m"] += s["length_m"]
        if s["name"]:
            type_summary[h]["named_segments"] += 1

        if s["name"]:
            key = f"{s['name']}|{h}"
            name_summary[key]["segments"] += 1
            name_summary[key]["total_length_m"] += s["length_m"]
            name_summary[key]["highway"] = h

    geojson = {
        "type": "FeatureCollection",
        "features": filtered_features,
    }
    OUT_GEOJSON.write_text(json.dumps(geojson, ensure_ascii=False), encoding="utf-8")

    with OUT_SEGMENTS_CSV.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "way_id",
                "highway",
                "name",
                "ref",
                "lanes",
                "maxspeed",
                "oneway",
                "bridge",
                "tunnel",
                "length_m",
            ],
        )
        writer.writeheader()
        writer.writerows(segments)

    with OUT_TYPE_CSV.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["highway", "segment_count", "named_segment_count", "total_length_m", "total_length_km"])
        for h, d in sorted(type_summary.items(), key=lambda kv: kv[1]["total_length_m"], reverse=True):
            writer.writerow(
                [
                    h,
                    d["segments"],
                    d["named_segments"],
                    round(d["total_length_m"], 2),
                    round(d["total_length_m"] / 1000.0, 3),
                ]
            )

    named_rows = []
    for key, d in name_summary.items():
        name, _ = key.split("|", 1)
        named_rows.append(
            {
                "road_name": name,
                "highway": d["highway"],
                "segment_count": d["segments"],
                "total_length_m": round(d["total_length_m"], 2),
                "total_length_km": round(d["total_length_m"] / 1000.0, 3),
            }
        )

    named_rows.sort(key=lambda r: r["total_length_m"], reverse=True)
    with OUT_NAME_CSV.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["road_name", "highway", "segment_count", "total_length_m", "total_length_km"],
        )
        writer.writeheader()
        writer.writerows(named_rows)

    stats = {
        "source": "OpenStreetMap Overpass bbox query",
        "raw_way_count": len([e for e in elements if e.get("type") == "way"]),
        "filtered_way_count": len(segments),
        "highway_type_count": len(type_summary),
        "named_road_count": len(named_rows),
        "total_length_m": round(sum(s["length_m"] for s in segments), 2),
        "total_length_km": round(sum(s["length_m"] for s in segments) / 1000.0, 3),
    }
    OUT_STATS_JSON.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(stats, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
