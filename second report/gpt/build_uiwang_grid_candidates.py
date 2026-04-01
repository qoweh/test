#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd
import requests
from pyproj import Transformer
from shapely.geometry import MultiPoint, Point, box, mapping, shape
from shapely.ops import transform

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = Path(__file__).resolve().parent

IN_CCTV = ROOT / "데이터_정리/02_가공데이터/traffic_cctv_uiwang.csv"
IN_BUS = ROOT / "데이터_정리/02_가공데이터/bus_stop_uiwang.csv"
IN_ACCIDENT = ROOT / "데이터_정리/02_가공데이터/qgis_ready/csv/accident_hotspots_raw_uiwang.csv"
IN_FATAL = ROOT / "데이터_정리/02_가공데이터/qgis_ready/csv/fatal_accidents_uiwang.csv"
IN_SCHOOL = ROOT / "데이터_정리/01_원본데이터/위치 활용/초중등학교_의왕시_H컬럼추출.csv"

WGS84 = "EPSG:4326"
METRIC_CRS = "EPSG:5179"


def load_points(csv_path: Path, lat_col: str, lon_col: str, keep_cols: Iterable[str] | None = None) -> pd.DataFrame:
    df = pd.read_csv(csv_path, encoding="utf-8-sig")
    if keep_cols:
        keep_cols = list(dict.fromkeys([*keep_cols, lat_col, lon_col]))
        existing = [c for c in keep_cols if c in df.columns]
        df = df[existing].copy()

    df[lat_col] = pd.to_numeric(df[lat_col], errors="coerce")
    df[lon_col] = pd.to_numeric(df[lon_col], errors="coerce")
    df = df.dropna(subset=[lat_col, lon_col]).copy()

    df = df.rename(columns={lat_col: "lat", lon_col: "lon"})
    df = df[(df["lat"].between(33.0, 39.5)) & (df["lon"].between(124.0, 132.0))].copy()
    df = df.drop_duplicates(subset=["lat", "lon"])
    return df.reset_index(drop=True)


def fetch_uiwang_boundary() -> tuple[object, str] | tuple[None, str]:
    url = "https://nominatim.openstreetmap.org/search"
    params = {
        "q": "의왕시, 경기도, 대한민국",
        "format": "jsonv2",
        "polygon_geojson": 1,
        "limit": 10,
    }
    headers = {"User-Agent": "uiwang-cctv-grid-analysis/1.0"}

    try:
        resp = requests.get(url, params=params, headers=headers, timeout=30)
        resp.raise_for_status()
        rows = resp.json()

        for row in rows:
            geo = row.get("geojson")
            display_name = str(row.get("display_name", ""))
            if not geo:
                continue
            if "의왕" not in display_name and "Uiwang" not in display_name:
                continue
            geom = shape(geo)
            if geom.geom_type in {"Polygon", "MultiPolygon"} and not geom.is_empty:
                return geom, "OSM Nominatim"

        return None, "OSM Nominatim returned no polygon"
    except Exception as exc:  # noqa: BLE001
        return None, f"OSM Nominatim failed: {exc}"


def fallback_boundary_from_points(point_frames: list[pd.DataFrame]) -> tuple[object, str]:
    coords = []
    for frame in point_frames:
        coords.extend([(lon, lat) for lon, lat in zip(frame["lon"], frame["lat"])])

    if not coords:
        raise RuntimeError("No points available to build fallback boundary")

    hull = MultiPoint(coords).convex_hull

    fwd = Transformer.from_crs(WGS84, METRIC_CRS, always_xy=True)
    rev = Transformer.from_crs(METRIC_CRS, WGS84, always_xy=True)

    hull_m = transform(fwd.transform, hull)
    buffered_m = hull_m.buffer(1200)
    buffered_wgs = transform(rev.transform, buffered_m)
    return buffered_wgs, "Fallback convex hull + 1200m buffer"


def filter_points_near_boundary(df: pd.DataFrame, boundary_wgs84, margin_deg: float = 0.01) -> pd.DataFrame:
    padded = boundary_wgs84.buffer(margin_deg)
    keep_mask = [padded.contains(Point(lon, lat)) for lon, lat in zip(df["lon"], df["lat"])]
    return df.loc[keep_mask].reset_index(drop=True)


def build_grid(boundary_m, cell_size_m: int) -> list:
    minx, miny, maxx, maxy = boundary_m.bounds
    start_x = np.floor(minx / cell_size_m) * cell_size_m
    start_y = np.floor(miny / cell_size_m) * cell_size_m
    end_x = np.ceil(maxx / cell_size_m) * cell_size_m
    end_y = np.ceil(maxy / cell_size_m) * cell_size_m

    xs = np.arange(start_x, end_x, cell_size_m)
    ys = np.arange(start_y, end_y, cell_size_m)

    geoms = []
    min_area = (cell_size_m * cell_size_m) * 0.05

    for x0 in xs:
        for y0 in ys:
            cell = box(x0, y0, x0 + cell_size_m, y0 + cell_size_m)
            if not cell.intersects(boundary_m):
                continue
            clipped = cell.intersection(boundary_m)
            if clipped.is_empty:
                continue
            if clipped.area < min_area:
                continue
            geoms.append(clipped)

    if not geoms:
        raise RuntimeError("Grid generation failed: no cells intersect boundary")

    return geoms


def project_points(df: pd.DataFrame, transformer: Transformer) -> np.ndarray:
    if df.empty:
        return np.empty((0, 2), dtype=float)
    x, y = transformer.transform(df["lon"].to_numpy(), df["lat"].to_numpy())
    return np.column_stack([x, y])


def nearest_distance_m(centroids_xy: np.ndarray, targets_xy: np.ndarray, chunk_size: int = 512) -> np.ndarray:
    n = len(centroids_xy)
    if targets_xy.size == 0:
        return np.full(n, np.nan, dtype=float)

    out = np.empty(n, dtype=float)
    for start in range(0, n, chunk_size):
        stop = min(start + chunk_size, n)
        c = centroids_xy[start:stop]
        dx = c[:, None, 0] - targets_xy[None, :, 0]
        dy = c[:, None, 1] - targets_xy[None, :, 1]
        out[start:stop] = np.sqrt((dx * dx) + (dy * dy)).min(axis=1)
    return out


def robust_score(arr: np.ndarray, larger_is_better: bool) -> np.ndarray:
    out = np.zeros_like(arr, dtype=float)
    valid = np.isfinite(arr)
    if not valid.any():
        return out

    vals = arr[valid]
    q10, q90 = np.percentile(vals, [10, 90])
    if np.isclose(q10, q90):
        out[valid] = 0.5
        return out

    if larger_is_better:
        out[valid] = (vals - q10) / (q90 - q10)
    else:
        out[valid] = (q90 - vals) / (q90 - q10)

    out = np.clip(out, 0.0, 1.0)
    return out


def to_serializable_record(record: dict) -> dict:
    out = {}
    for k, v in record.items():
        if isinstance(v, (np.floating, np.integer)):
            out[k] = float(v)
        elif isinstance(v, (np.bool_, bool)):
            out[k] = bool(v)
        else:
            out[k] = v
    return out


def write_geojson(path: Path, geoms_wgs84: list, records: list[dict], layer_name: str) -> None:
    features = []
    for geom, rec in zip(geoms_wgs84, records):
        features.append(
            {
                "type": "Feature",
                "geometry": mapping(geom),
                "properties": to_serializable_record(rec),
            }
        )

    payload = {
        "type": "FeatureCollection",
        "name": layer_name,
        "crs": {"type": "name", "properties": {"name": WGS84}},
        "features": features,
    }

    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build grid-based CCTV candidate scoring layer for Uiwang.")
    parser.add_argument("--grid-size", type=int, default=250, help="Grid cell size in meters (default: 250)")
    parser.add_argument("--min-cctv-gap", type=float, default=200.0, help="Minimum distance from CCTV for candidate filtering")
    parser.add_argument("--top-n", type=int, default=120, help="Number of top candidate points to export")
    parser.add_argument("--skip-osm-boundary", action="store_true", help="Skip OSM boundary lookup and use fallback boundary")
    args = parser.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    cctv = load_points(IN_CCTV, "위도", "경도", keep_cols=["관리기관명", "설치목적구분"])
    bus = load_points(IN_BUS, "위도", "경도", keep_cols=["정류소명", "정류소id"])
    accident = load_points(
        IN_ACCIDENT,
        "위도",
        "경도",
        keep_cols=["시군명", "사고년도", "발생건수", "사망자수", "사고지역위치명"],
    )
    fatal = load_points(IN_FATAL, "위도", "경도", keep_cols=["시군명", "발생년도", "사망자수", "발생일자"])
    school = load_points(IN_SCHOOL, "위도", "경도", keep_cols=["학교ID", "학교명", "학교급구분"])

    boundary_wgs84 = None
    boundary_source = ""
    if not args.skip_osm_boundary:
        boundary_wgs84, boundary_source = fetch_uiwang_boundary()

    if boundary_wgs84 is None:
        boundary_wgs84, boundary_source = fallback_boundary_from_points([cctv, bus, accident, fatal, school])

    cctv = filter_points_near_boundary(cctv, boundary_wgs84)
    bus = filter_points_near_boundary(bus, boundary_wgs84)
    accident = filter_points_near_boundary(accident, boundary_wgs84)
    fatal = filter_points_near_boundary(fatal, boundary_wgs84)
    school = filter_points_near_boundary(school, boundary_wgs84)

    to_metric = Transformer.from_crs(WGS84, METRIC_CRS, always_xy=True)
    to_wgs84 = Transformer.from_crs(METRIC_CRS, WGS84, always_xy=True)

    boundary_m = transform(to_metric.transform, boundary_wgs84)
    grid_m = build_grid(boundary_m, args.grid_size)
    centroids_m = np.array([(g.centroid.x, g.centroid.y) for g in grid_m], dtype=float)

    cctv_xy = project_points(cctv, to_metric)
    bus_xy = project_points(bus, to_metric)
    accident_xy = project_points(accident, to_metric)
    fatal_xy = project_points(fatal, to_metric)
    school_xy = project_points(school, to_metric)

    d_cctv = nearest_distance_m(centroids_m, cctv_xy)
    d_bus = nearest_distance_m(centroids_m, bus_xy)
    d_accident = nearest_distance_m(centroids_m, accident_xy)
    d_fatal = nearest_distance_m(centroids_m, fatal_xy)
    d_school = nearest_distance_m(centroids_m, school_xy)

    score_gap = robust_score(d_cctv, larger_is_better=True)
    score_bus = robust_score(d_bus, larger_is_better=False)
    score_accident = robust_score(d_accident, larger_is_better=False)
    score_fatal = robust_score(d_fatal, larger_is_better=False)
    score_school = robust_score(d_school, larger_is_better=False)

    vulnerability = (
        (0.35 * score_accident)
        + (0.30 * score_fatal)
        + (0.20 * score_bus)
        + (0.15 * score_school)
    )

    total_score = (0.60 * score_gap) + (0.40 * vulnerability)
    proximity_penalty = np.clip((150.0 - d_cctv) / 150.0, 0.0, 1.0) * 0.25
    total_score = np.clip(total_score - proximity_penalty, 0.0, 1.0)

    rank = pd.Series(total_score).rank(ascending=False, method="dense").astype(int).to_numpy()

    vuln_threshold = float(np.nanpercentile(vulnerability, 55))
    score_threshold = float(np.nanpercentile(total_score, 70))

    candidate_flag = (
        (d_cctv >= args.min_cctv_gap)
        & (vulnerability >= vuln_threshold)
        & (total_score >= score_threshold)
    )

    centroids_wgs = [transform(to_wgs84.transform, g.centroid) for g in grid_m]
    grid_wgs = [transform(to_wgs84.transform, g) for g in grid_m]

    records = []
    for idx, (pt, dc, db, da, df, ds, sg, sb, sa, sf, ss, vv, tt, rr, cand) in enumerate(
        zip(
            centroids_wgs,
            d_cctv,
            d_bus,
            d_accident,
            d_fatal,
            d_school,
            score_gap,
            score_bus,
            score_accident,
            score_fatal,
            score_school,
            vulnerability,
            total_score,
            rank,
            candidate_flag,
        ),
        start=1,
    ):
        records.append(
            {
                "grid_id": idx,
                "centroid_lon": round(float(pt.x), 8),
                "centroid_lat": round(float(pt.y), 8),
                "dist_cctv_m": round(float(dc), 2),
                "dist_bus_m": round(float(db), 2),
                "dist_accident_m": round(float(da), 2),
                "dist_fatal_m": round(float(df), 2),
                "dist_school_m": round(float(ds), 2),
                "score_gap_0_1": round(float(sg), 6),
                "score_bus_0_1": round(float(sb), 6),
                "score_accident_0_1": round(float(sa), 6),
                "score_fatal_0_1": round(float(sf), 6),
                "score_school_0_1": round(float(ss), 6),
                "vulnerability_0_1": round(float(vv), 6),
                "total_score_0_100": round(float(tt * 100.0), 3),
                "priority_rank": int(rr),
                "candidate_flag": bool(cand),
            }
        )

    grid_df = pd.DataFrame(records).sort_values("total_score_0_100", ascending=False).reset_index(drop=True)

    candidate_df = grid_df[grid_df["candidate_flag"]].copy()
    candidate_df = candidate_df.nsmallest(999999, "priority_rank").head(args.top_n).copy()

    csv_grid = OUT_DIR / f"uiwang_grid_score_{args.grid_size}m.csv"
    geojson_grid = OUT_DIR / f"uiwang_grid_score_{args.grid_size}m.geojson"
    csv_top = OUT_DIR / f"uiwang_candidate_top{args.top_n}_{args.grid_size}m.csv"
    geojson_top = OUT_DIR / f"uiwang_candidate_top{args.top_n}_{args.grid_size}m.geojson"
    boundary_geojson = OUT_DIR / "uiwang_boundary.geojson"
    summary_json = OUT_DIR / "uiwang_grid_summary.json"

    grid_df.to_csv(csv_grid, index=False, encoding="utf-8-sig")
    candidate_df.to_csv(csv_top, index=False, encoding="utf-8-sig")

    write_geojson(geojson_grid, grid_wgs, records, layer_name=f"uiwang_grid_score_{args.grid_size}m")

    top_records = candidate_df.to_dict(orient="records")
    top_features = []
    for rec in top_records:
        top_features.append(
            {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [float(rec["centroid_lon"]), float(rec["centroid_lat"])],
                },
                "properties": to_serializable_record(rec),
            }
        )

    with geojson_top.open("w", encoding="utf-8") as f:
        json.dump(
            {
                "type": "FeatureCollection",
                "name": f"uiwang_candidate_top{args.top_n}_{args.grid_size}m",
                "crs": {"type": "name", "properties": {"name": WGS84}},
                "features": top_features,
            },
            f,
            ensure_ascii=False,
            indent=2,
        )

    with boundary_geojson.open("w", encoding="utf-8") as f:
        json.dump(
            {
                "type": "FeatureCollection",
                "name": "uiwang_boundary",
                "crs": {"type": "name", "properties": {"name": WGS84}},
                "features": [
                    {
                        "type": "Feature",
                        "geometry": mapping(boundary_wgs84),
                        "properties": {
                            "source": boundary_source,
                        },
                    }
                ],
            },
            f,
            ensure_ascii=False,
            indent=2,
        )

    summary = {
        "grid_size_m": args.grid_size,
        "min_cctv_gap_m": args.min_cctv_gap,
        "top_n": args.top_n,
        "boundary_source": boundary_source,
        "input_counts": {
            "cctv": int(len(cctv)),
            "bus_stop": int(len(bus)),
            "accident_hotspot": int(len(accident)),
            "fatal_accident": int(len(fatal)),
            "school": int(len(school)),
        },
        "output_counts": {
            "grid_cells": int(len(grid_df)),
            "candidate_cells": int(candidate_df.shape[0]),
        },
        "output_files": {
            "grid_csv": csv_grid.name,
            "grid_geojson": geojson_grid.name,
            "top_csv": csv_top.name,
            "top_geojson": geojson_top.name,
            "boundary_geojson": boundary_geojson.name,
        },
    }

    with summary_json.open("w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
