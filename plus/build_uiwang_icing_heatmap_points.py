#!/usr/bin/env python3
from __future__ import annotations

import json
import math
from pathlib import Path


ROOT = Path(__file__).resolve().parent
IN_LINES = ROOT / "uiwang_all_roads_with_traffic_lines_in_boundary_inferred.geojson"
OUT_POINTS = ROOT / "uiwang_road_icing_heatmap_points.geojson"
OUT_SUMMARY = ROOT / "uiwang_road_icing_heatmap_points_summary.json"

EARTH_R_M = 6371000.0


def to_float(value) -> float:
    try:
        return float(value)
    except Exception:
        return 0.0


def haversine_m(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2.0) ** 2
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return EARTH_R_M * c


def iter_lines(geometry: dict):
    gtype = (geometry or {}).get("type")
    coords = (geometry or {}).get("coordinates") or []
    if gtype == "LineString":
        yield coords
    elif gtype == "MultiLineString":
        for line in coords:
            yield line


def main() -> None:
    if not IN_LINES.exists():
        raise FileNotFoundError(f"Missing input: {IN_LINES}")

    payload = json.loads(IN_LINES.read_text(encoding="utf-8"))
    features = payload.get("features", [])

    out_features = []
    positive_volume_points = 0
    vol_sum = 0.0
    weight_sum = 0.0

    for ft in features:
        props = ft.get("properties", {}) or {}
        geom = ft.get("geometry", {}) or {}
        vol = max(to_float(props.get("vol_mean", 0.0)), 0.0)

        for line in iter_lines(geom):
            if not isinstance(line, list) or len(line) < 2:
                continue

            for i in range(len(line) - 1):
                p1 = line[i]
                p2 = line[i + 1]
                if not (isinstance(p1, list) and isinstance(p2, list) and len(p1) >= 2 and len(p2) >= 2):
                    continue

                lon1, lat1 = float(p1[0]), float(p1[1])
                lon2, lat2 = float(p2[0]), float(p2[1])
                mid_lon = (lon1 + lon2) / 2.0
                mid_lat = (lat1 + lat2) / 2.0
                seg_len_m = haversine_m(lon1, lat1, lon2, lat2)

                # KDE 가중치는 교통량 로그값과 선분 길이를 함께 반영해 군집이 과도하게 쏠리지 않게 만든다.
                kde_weight = math.log1p(vol) * max(seg_len_m, 1.0) / 25.0

                out_props = {
                    "way_id": str(props.get("way_id", "")),
                    "highway": str(props.get("highway", "")),
                    "name": str(props.get("name", "")),
                    "traffic_match": str(props.get("traffic_match", "")),
                    "vol_mean": vol,
                    "segment_len_m": round(seg_len_m, 3),
                    "kde_weight": round(kde_weight, 6),
                }

                out_features.append(
                    {
                        "type": "Feature",
                        "geometry": {"type": "Point", "coordinates": [mid_lon, mid_lat]},
                        "properties": out_props,
                    }
                )
                if vol > 0:
                    positive_volume_points += 1
                vol_sum += vol
                weight_sum += kde_weight

    out_geojson = {
        "type": "FeatureCollection",
        "name": "uiwang_road_icing_heatmap_points",
        "crs": {"type": "name", "properties": {"name": "EPSG:4326"}},
        "features": out_features,
    }
    OUT_POINTS.write_text(json.dumps(out_geojson, ensure_ascii=False), encoding="utf-8")

    summary = {
        "input": str(IN_LINES.name),
        "output": str(OUT_POINTS.name),
        "summary_output": str(OUT_SUMMARY.name),
        "source_feature_count": int(len(features)),
        "point_count": int(len(out_features)),
        "positive_volume_points": int(positive_volume_points),
        "mean_vol": float(vol_sum / len(out_features) if out_features else 0.0),
        "mean_kde_weight": float(weight_sum / len(out_features) if out_features else 0.0),
    }
    OUT_SUMMARY.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
