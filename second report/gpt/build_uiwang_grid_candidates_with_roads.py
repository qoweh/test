#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from pyproj import Transformer
from shapely.geometry import Point, box, mapping, shape
from shapely.ops import transform


WGS84 = "EPSG:4326"
METRIC_CRS = "EPSG:5179"
DISTANCE_TOLERANCE_SQUARED = 1e-12


GPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = GPT_DIR.parent.parent
THIS_DIR = PROJECT_DIR / "this"
PLUS_DIR = PROJECT_DIR / "plus"

IN_CCTV = THIS_DIR / "무인교통단속카메라.gpkg"
IN_BUS = THIS_DIR / "버스정류소.gpkg"
IN_ACCIDENT = THIS_DIR / "사고다발지.gpkg"
IN_FATAL = THIS_DIR / "사망교통사고.gpkg"
IN_SCHOOL = THIS_DIR / "초중고등학교.gpkg"
IN_ROADS = PLUS_DIR / "uiwang_all_roads_with_traffic_lines_in_boundary.geojson"

LAYER_CCTV = "무인교통단속카메라"
LAYER_BUS = "버스정류소"
LAYER_ACCIDENT = "사고다발지_내보내기"
LAYER_FATAL = "사망교통사고_내보내기"
LAYER_SCHOOL = "초중고등학교_내보내기"


def load_boundary_polygon() -> tuple[object, str]:
    candidates = [
        GPT_DIR / "this_uiwang_boundary.geojson",
        GPT_DIR / "uiwang_boundary.geojson",
    ]

    for path in candidates:
        if not path.exists():
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        polys = []
        for ft in payload.get("features", []):
            geom = ft.get("geometry")
            if not geom:
                continue
            g = shape(geom)
            if g.geom_type in {"Polygon", "MultiPolygon"} and not g.is_empty:
                polys.append(g)

        if polys:
            best = max(polys, key=lambda x: x.area)
            if not best.is_valid:
                best = best.buffer(0)
            if not best.is_empty:
                return best, path.name

    raise FileNotFoundError("Boundary file not found in gpt folder")


def load_points_from_gpkg(path: Path, layer: str, source_type: str) -> gpd.GeoDataFrame:
    gdf = gpd.read_file(path, layer=layer, engine="pyogrio")

    if gdf.crs is None:
        gdf = gdf.set_crs(WGS84)
    else:
        gdf = gdf.to_crs(WGS84)

    gdf = gdf[gdf.geometry.notna()].copy()
    gdf = gdf[gdf.geometry.geom_type.isin(["Point", "MultiPoint"])].copy()

    # Convert multipoint to centroid for consistent nearest-distance logic.
    multi_mask = gdf.geometry.geom_type == "MultiPoint"
    if multi_mask.any():
        tmp = gdf.loc[multi_mask].to_crs(METRIC_CRS)
        tmp["geometry"] = tmp.geometry.centroid
        gdf.loc[multi_mask, "geometry"] = tmp.to_crs(WGS84).geometry.values

    gdf["lon"] = gdf.geometry.x
    gdf["lat"] = gdf.geometry.y

    gdf = gdf[
        (gdf["lon"].between(124.0, 132.0))
        & (gdf["lat"].between(33.0, 39.5))
    ].copy()

    gdf = gdf.drop_duplicates(subset=["lon", "lat"]).reset_index(drop=True)
    gdf["source_type"] = source_type
    return gdf[["source_type", "lon", "lat", "geometry"]].copy()


def filter_points_near_boundary(gdf: gpd.GeoDataFrame, boundary_wgs84, margin_m: float = 600.0) -> gpd.GeoDataFrame:
    to_metric = Transformer.from_crs(WGS84, METRIC_CRS, always_xy=True)
    to_wgs = Transformer.from_crs(METRIC_CRS, WGS84, always_xy=True)

    boundary_m = transform(to_metric.transform, boundary_wgs84)
    padded_wgs = transform(to_wgs.transform, boundary_m.buffer(margin_m))

    mask = gdf.geometry.within(padded_wgs)
    return gdf.loc[mask].reset_index(drop=True)


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


def project_points(gdf: gpd.GeoDataFrame, transformer: Transformer) -> np.ndarray:
    if gdf.empty:
        return np.empty((0, 2), dtype=float)

    x, y = transformer.transform(gdf["lon"].to_numpy(), gdf["lat"].to_numpy())
    return np.column_stack([x, y])


def nearest_distance_m(centroids_xy: np.ndarray, targets_xy: np.ndarray, chunk_size: int = 512) -> np.ndarray:
    n = len(centroids_xy)
    if targets_xy.size == 0:
        return np.full(n, np.nan, dtype=float)

    out = np.empty(n, dtype=float)
    for s in range(0, n, chunk_size):
        e = min(s + chunk_size, n)
        c = centroids_xy[s:e]
        dx = c[:, None, 0] - targets_xy[None, :, 0]
        dy = c[:, None, 1] - targets_xy[None, :, 1]
        out[s:e] = np.sqrt((dx * dx) + (dy * dy)).min(axis=1)

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

    return np.clip(out, 0.0, 1.0)


def export_version(
    base_df: pd.DataFrame,
    grid_wgs: list,
    version_name: str,
    score_column: str,
    top_n: int,
) -> dict:
    df = base_df.copy()

    # Candidate condition: sufficiently far from existing CCTV + sufficiently near a road segment.
    candidate_mask = (df["dist_cctv_m"] >= df["min_cctv_gap_m"]) & (df["dist_road_m"] <= df["max_road_dist_m"])

    ranked = df.loc[candidate_mask].sort_values(score_column, ascending=False).copy()
    top = ranked.head(top_n).copy()

    df["candidate_flag"] = False
    if not top.empty:
        df.loc[df["grid_id"].isin(top["grid_id"]), "candidate_flag"] = True

    df["priority_rank"] = df[score_column].rank(ascending=False, method="dense").astype(int)

    class_labels = ["Very Low", "Low", "Medium", "High", "Very High"]
    try:
        df["score_class"] = pd.qcut(df[score_column], q=5, labels=class_labels, duplicates="drop")
    except ValueError:
        df["score_class"] = "Medium"

    prefix = f"this_uiwang_roads_{version_name}"
    csv_grid = GPT_DIR / f"{prefix}_grid_score_250m.csv"
    geojson_grid = GPT_DIR / f"{prefix}_grid_score_250m.geojson"
    gpkg_grid = GPT_DIR / f"{prefix}_grid_score_250m.gpkg"
    csv_top = GPT_DIR / f"{prefix}_candidate_top{top_n}_250m.csv"
    geojson_top = GPT_DIR / f"{prefix}_candidate_cells_top{top_n}_250m.geojson"
    geojson_points = GPT_DIR / f"{prefix}_candidate_points_top{top_n}_250m.geojson"

    df_out = df.sort_values(score_column, ascending=False).reset_index(drop=True)
    df_out.to_csv(csv_grid, index=False, encoding="utf-8-sig")
    top.to_csv(csv_top, index=False, encoding="utf-8-sig")

    records = df_out.to_dict(orient="records")
    geom_map = {int(gid): geom for gid, geom in zip(df["grid_id"].tolist(), grid_wgs)}

    grid_features = []
    for rec in records:
        gid = int(rec["grid_id"])
        grid_features.append(
            {
                "type": "Feature",
                "geometry": mapping(geom_map[gid]),
                "properties": rec,
            }
        )

    geojson_payload = {
        "type": "FeatureCollection",
        "name": f"{prefix}_grid_score_250m",
        "crs": {"type": "name", "properties": {"name": WGS84}},
        "features": grid_features,
    }
    geojson_grid.write_text(json.dumps(geojson_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    gdf_grid = gpd.GeoDataFrame(df_out, geometry=[geom_map[int(g)] for g in df_out["grid_id"]], crs=WGS84)
    gdf_grid.to_file(gpkg_grid, layer="grid_score", driver="GPKG", engine="pyogrio")

    top_cells = []
    top_points = []
    for _, rec in top.iterrows():
        gid = int(rec["grid_id"])
        geom = geom_map[gid]
        top_cells.append(
            {
                "type": "Feature",
                "geometry": mapping(geom),
                "properties": rec.to_dict(),
            }
        )
        top_points.append(
            {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [float(rec["centroid_lon"]), float(rec["centroid_lat"])],
                },
                "properties": rec.to_dict(),
            }
        )

    geojson_top.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "name": f"{prefix}_candidate_cells_top{top_n}_250m",
                "crs": {"type": "name", "properties": {"name": WGS84}},
                "features": top_cells,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    geojson_points.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "name": f"{prefix}_candidate_points_top{top_n}_250m",
                "crs": {"type": "name", "properties": {"name": WGS84}},
                "features": top_points,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    return {
        "version": version_name,
        "score_column": score_column,
        "candidate_count": int(top.shape[0]),
        "output_files": {
            "grid_csv": csv_grid.name,
            "grid_geojson": geojson_grid.name,
            "grid_gpkg": gpkg_grid.name,
            "top_csv": csv_top.name,
            "top_cells_geojson": geojson_top.name,
            "top_points_geojson": geojson_points.name,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Rebuild Uiwang CCTV candidate grids with road segment + traffic factors")
    parser.add_argument("--grid-size", type=int, default=250)
    parser.add_argument("--top-n", type=int, default=150)
    parser.add_argument("--min-cctv-gap", type=float, default=200.0)
    parser.add_argument("--max-road-dist", type=float, default=150.0)
    args = parser.parse_args()

    boundary_wgs84, boundary_source = load_boundary_polygon()

    cctv = load_points_from_gpkg(IN_CCTV, LAYER_CCTV, "cctv")
    bus = load_points_from_gpkg(IN_BUS, LAYER_BUS, "bus")
    accident = load_points_from_gpkg(IN_ACCIDENT, LAYER_ACCIDENT, "accident")
    fatal = load_points_from_gpkg(IN_FATAL, LAYER_FATAL, "fatal")
    school = load_points_from_gpkg(IN_SCHOOL, LAYER_SCHOOL, "school")

    cctv = filter_points_near_boundary(cctv, boundary_wgs84)
    bus = filter_points_near_boundary(bus, boundary_wgs84)
    accident = filter_points_near_boundary(accident, boundary_wgs84)
    fatal = filter_points_near_boundary(fatal, boundary_wgs84)
    school = filter_points_near_boundary(school, boundary_wgs84)

    roads = gpd.read_file(IN_ROADS, engine="pyogrio")
    if roads.crs is None:
        roads = roads.set_crs(WGS84)
    else:
        roads = roads.to_crs(WGS84)
    roads = roads[roads.geometry.notna()].copy()

    if "vol_mean" in roads.columns:
        roads["vol_mean_num"] = pd.to_numeric(roads["vol_mean"], errors="coerce").fillna(0.0)
    else:
        roads["vol_mean_num"] = 0.0

    if "way_id" in roads.columns:
        roads["way_id_str"] = roads["way_id"].fillna("").astype(str)
    else:
        roads["way_id_str"] = ""

    if "name" not in roads.columns:
        roads["name"] = ""
    if "highway" not in roads.columns:
        roads["highway"] = ""

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

    roads_m = roads.to_crs(METRIC_CRS)
    centroid_points_m = gpd.GeoDataFrame(
        {"grid_id": np.arange(1, len(grid_m) + 1, dtype=int)},
        geometry=[Point(float(x), float(y)) for x, y in centroids_m],
        crs=METRIC_CRS,
    )

    nearest_roads = gpd.sjoin_nearest(
        centroid_points_m,
        roads_m[["way_id_str", "name", "highway", "vol_mean_num", "geometry"]],
        how="left",
        distance_col="dist_road_m",
    )
    nearest_roads = nearest_roads.sort_values(["grid_id", "dist_road_m"]).drop_duplicates(
        subset=["grid_id"],
        keep="first",
    )
    nearest_roads = nearest_roads.set_index("grid_id").reindex(
        centroid_points_m["grid_id"].to_numpy()
    ).reset_index()

    d_road = nearest_roads["dist_road_m"].to_numpy(dtype=float)
    nearest_vol = nearest_roads["vol_mean_num"].to_numpy(dtype=float)
    nearest_way_id = nearest_roads["way_id_str"].fillna("").astype(str).to_numpy()
    nearest_road_name = nearest_roads["name"].fillna("").astype(str).to_numpy()
    nearest_road_highway = nearest_roads["highway"].fillna("").astype(str).to_numpy()

    s_cctv = robust_score(d_cctv, larger_is_better=True)
    s_school = robust_score(d_school, larger_is_better=False)
    s_bus = robust_score(d_bus, larger_is_better=False)
    s_accident = robust_score(d_accident, larger_is_better=False)
    s_fatal = robust_score(d_fatal, larger_is_better=False)
    s_road = robust_score(d_road, larger_is_better=False)
    s_traffic = robust_score(nearest_vol, larger_is_better=True)

    score_equal = np.mean(
        np.column_stack([s_cctv, s_school, s_bus, s_accident, s_fatal, s_road, s_traffic]),
        axis=1,
    )

    # User-requested weighted version: fatal 5, cctv_gap 2, school 3, bus 3, accident 5, traffic 5.
    w_total = 2 + 3 + 3 + 5 + 5 + 5
    score_weighted = (
        (2 * s_cctv)
        + (3 * s_school)
        + (3 * s_bus)
        + (5 * s_accident)
        + (5 * s_fatal)
        + (5 * s_traffic)
    ) / w_total

    centroids_wgs = [transform(to_wgs84.transform, Point(x, y)) for x, y in centroids_m]

    base_df = pd.DataFrame(
        {
            "grid_id": np.arange(1, len(grid_m) + 1, dtype=int),
            "centroid_lon": [round(float(p.x), 8) for p in centroids_wgs],
            "centroid_lat": [round(float(p.y), 8) for p in centroids_wgs],
            "dist_cctv_m": np.round(d_cctv, 2),
            "dist_school_m": np.round(d_school, 2),
            "dist_bus_m": np.round(d_bus, 2),
            "dist_accident_m": np.round(d_accident, 2),
            "dist_fatal_m": np.round(d_fatal, 2),
            "dist_road_m": np.round(d_road, 2),
            "nearest_road_way_id": nearest_way_id,
            "nearest_road_name": nearest_road_name,
            "nearest_road_highway": nearest_road_highway,
            "nearest_road_vol_mean": np.round(nearest_vol, 3),
            "score_cctv_gap_0_1": np.round(s_cctv, 6),
            "score_school_0_1": np.round(s_school, 6),
            "score_bus_0_1": np.round(s_bus, 6),
            "score_accident_0_1": np.round(s_accident, 6),
            "score_fatal_0_1": np.round(s_fatal, 6),
            "score_road_proximity_0_1": np.round(s_road, 6),
            "score_traffic_0_1": np.round(s_traffic, 6),
            "total_score_equal_0_100": np.round(score_equal * 100.0, 3),
            "total_score_weighted_0_100": np.round(score_weighted * 100.0, 3),
            "min_cctv_gap_m": float(args.min_cctv_gap),
            "max_road_dist_m": float(args.max_road_dist),
        }
    )

    grid_wgs = [transform(to_wgs84.transform, g) for g in grid_m]

    eq_summary = export_version(
        base_df=base_df,
        grid_wgs=grid_wgs,
        version_name="equal",
        score_column="total_score_equal_0_100",
        top_n=args.top_n,
    )

    wt_summary = export_version(
        base_df=base_df,
        grid_wgs=grid_wgs,
        version_name="weighted",
        score_column="total_score_weighted_0_100",
        top_n=args.top_n,
    )

    merged_inputs = pd.concat(
        [
            cctv[["source_type", "geometry"]],
            bus[["source_type", "geometry"]],
            accident[["source_type", "geometry"]],
            fatal[["source_type", "geometry"]],
            school[["source_type", "geometry"]],
        ],
        ignore_index=True,
    )
    gdf_inputs = gpd.GeoDataFrame(merged_inputs, geometry="geometry", crs=WGS84)
    input_path = GPT_DIR / "this_uiwang_inputs_points_with_roads.geojson"
    gdf_inputs.to_file(input_path, driver="GeoJSON", engine="pyogrio")

    if "traffic_match" in roads.columns:
        roads_with_traffic = int((roads["traffic_match"].fillna("").astype(str) == "matched").sum())
    else:
        roads_with_traffic = 0

    summary = {
        "boundary_source": boundary_source,
        "road_source": str(IN_ROADS),
        "grid_size_m": args.grid_size,
        "top_n": args.top_n,
        "filters": {
            "min_cctv_gap_m": args.min_cctv_gap,
            "max_road_dist_m": args.max_road_dist,
        },
        "input_counts": {
            "cctv": int(len(cctv)),
            "bus": int(len(bus)),
            "accident": int(len(accident)),
            "fatal": int(len(fatal)),
            "school": int(len(school)),
            "roads": int(len(roads)),
            "roads_with_traffic": roads_with_traffic,
        },
        "versions": {
            "equal": eq_summary,
            "weighted": wt_summary,
        },
        "aux_output": {
            "inputs_geojson": input_path.name,
        },
    }

    summary_path = GPT_DIR / "this_uiwang_grid_summary_with_roads.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
