#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parent.parent
PLUS = ROOT / "plus"

IN_MERGED_CSV = PLUS / "uiwang_all_roads_with_traffic.csv"
IN_LINES_FULL = PLUS / "uiwang_all_roads_with_traffic_lines.geojson"
IN_LINES_BOUNDARY = PLUS / "uiwang_all_roads_with_traffic_lines_in_boundary.geojson"

OUT_MERGED_CSV = PLUS / "uiwang_all_roads_with_traffic_inferred.csv"
OUT_LINES_FULL = PLUS / "uiwang_all_roads_with_traffic_lines_inferred.geojson"
OUT_LINES_BOUNDARY = PLUS / "uiwang_all_roads_with_traffic_lines_in_boundary_inferred.geojson"
OUT_COVERAGE_JSON = PLUS / "uiwang_traffic_data_coverage_inferred.json"

WGS84 = "EPSG:4326"
METRIC_CRS = "EPSG:5179"
MAX_NEAREST_DISTANCE_M = 250.0


DRIVABLE_HIGHWAYS = {
    "motorway",
    "motorway_link",
    "trunk",
    "trunk_link",
    "primary",
    "primary_link",
    "secondary",
    "secondary_link",
    "tertiary",
    "tertiary_link",
    "residential",
    "service",
    "unclassified",
    "living_street",
    "road",
}


ROAD_FAMILY = {
    "motorway": "motorway",
    "motorway_link": "motorway",
    "trunk": "trunk",
    "trunk_link": "trunk",
    "primary": "primary",
    "primary_link": "primary",
    "secondary": "secondary",
    "secondary_link": "secondary",
    "tertiary": "tertiary",
    "tertiary_link": "tertiary",
    "residential": "local",
    "service": "local",
    "unclassified": "local",
    "living_street": "local",
    "road": "local",
}


def normalize_name(name: str) -> str:
    if not name:
        return ""
    return re.sub(r"\s+", "", str(name)).strip()


def format_num(value, digits: int = 3) -> str:
    if pd.isna(value):
        return ""
    text = f"{float(value):.{digits}f}".rstrip("0").rstrip(".")
    return text if text else "0"


def load_lines_geometry() -> pd.DataFrame:
    lines = gpd.read_file(IN_LINES_FULL, engine="pyogrio")
    if lines.crs is None:
        lines = lines.set_crs(WGS84)
    else:
        lines = lines.to_crs(WGS84)

    lines["way_id_str"] = lines["way_id"].fillna("").astype(str).str.strip()
    geom = lines[["way_id_str", "geometry"]].drop_duplicates(subset=["way_id_str"]).copy()
    return geom


def append_inferred_source(base_source: str, method: str) -> str:
    marker = f"inferred({method})"
    src = (base_source or "").strip()
    if marker in src:
        return src
    if not src:
        return marker
    return f"{src} + {marker}"


def update_geojson_properties(in_path: Path, out_path: Path, attrs_by_way: dict[str, dict]) -> dict:
    payload = json.loads(in_path.read_text(encoding="utf-8"))
    features = payload.get("features", [])

    updated = 0
    way_ids = []
    for ft in features:
        props = ft.get("properties", {})
        way_id = str(props.get("way_id", "")).strip()
        if way_id:
            way_ids.append(way_id)
        row = attrs_by_way.get(way_id)
        if row is None:
            continue
        props.update(row)
        ft["properties"] = props
        updated += 1

    out_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return {
        "feature_count": len(features),
        "updated_count": updated,
        "way_ids": way_ids,
    }


def main() -> None:
    if not IN_MERGED_CSV.exists():
        raise FileNotFoundError(IN_MERGED_CSV)
    if not IN_LINES_FULL.exists():
        raise FileNotFoundError(IN_LINES_FULL)
    if not IN_LINES_BOUNDARY.exists():
        raise FileNotFoundError(IN_LINES_BOUNDARY)

    raw_df = pd.read_csv(IN_MERGED_CSV, dtype=str).fillna("")
    original_columns = list(raw_df.columns)
    raw_df["way_id_str"] = raw_df["way_id"].astype(str).str.strip()

    for col in ["vol_mean", "vol_min", "vol_max", "spd_mean", "trvlTime_mean", "traffic_rows_used"]:
        raw_df[f"{col}_num"] = pd.to_numeric(raw_df.get(col, ""), errors="coerce")

    geom_df = load_lines_geometry()
    work = raw_df.merge(geom_df, on="way_id_str", how="left", validate="one_to_one")
    gdf = gpd.GeoDataFrame(work, geometry="geometry", crs=WGS84)

    gdf["road_family"] = gdf["highway"].map(ROAD_FAMILY)
    gdf["name_norm"] = gdf["name"].map(normalize_name)

    observed_mask = (gdf["traffic_match"] == "matched") & gdf["vol_mean_num"].notna()
    candidate_mask = (~observed_mask) & gdf["highway"].isin(DRIVABLE_HIGHWAYS)

    gdf["traffic_match_original"] = gdf["traffic_match"]
    gdf["traffic_observed_match"] = np.where(observed_mask, "yes", "no")
    gdf["traffic_inferred"] = "no"
    gdf["inferred_distance_m"] = np.nan

    method_counts = Counter()

    def apply_inference(
        idx: int,
        method: str,
        vol,
        spd,
        trvl,
        route_name: str = "",
        route_no: str = "",
        rows_used: str = "",
        distance_m=np.nan,
    ) -> None:
        if pd.notna(vol):
            gdf.at[idx, "vol_mean_num"] = float(vol)
            if pd.isna(gdf.at[idx, "vol_min_num"]):
                gdf.at[idx, "vol_min_num"] = float(vol)
            if pd.isna(gdf.at[idx, "vol_max_num"]):
                gdf.at[idx, "vol_max_num"] = float(vol)
        if pd.notna(spd):
            gdf.at[idx, "spd_mean_num"] = float(spd)
        if pd.notna(trvl):
            gdf.at[idx, "trvlTime_mean_num"] = float(trvl)

        if route_name:
            gdf.at[idx, "matched_route_name_norm"] = route_name
        if route_no:
            gdf.at[idx, "matched_route_no"] = route_no
        if rows_used not in {None, "", "nan"}:
            gdf.at[idx, "traffic_rows_used"] = str(rows_used)

        gdf.at[idx, "traffic_match"] = "inferred"
        gdf.at[idx, "traffic_match_method"] = method
        gdf.at[idx, "traffic_inferred"] = "yes"
        gdf.at[idx, "traffic_observed_match"] = "no"
        if pd.notna(distance_m):
            gdf.at[idx, "inferred_distance_m"] = float(distance_m)

        base_source = str(gdf.at[idx, "source_traffic"])
        gdf.at[idx, "source_traffic"] = append_inferred_source(base_source, method)

        method_counts[method] += 1

    observed = gdf.loc[observed_mask].copy()
    remaining = set(gdf.index[candidate_mask])

    # 1) Same normalized road name median.
    if not observed.empty:
        name_stats = (
            observed.loc[observed["name_norm"] != "", ["name_norm", "vol_mean_num", "spd_mean_num", "trvlTime_mean_num"]]
            .groupby("name_norm", as_index=True)
            .median()
        )
        name_count = observed.loc[observed["name_norm"] != ""].groupby("name_norm").size().to_dict()

        name_candidates = gdf.index[
            candidate_mask & (gdf["name_norm"] != "") & gdf["name_norm"].isin(name_stats.index)
        ]
        for idx in name_candidates:
            stats = name_stats.loc[gdf.at[idx, "name_norm"]]
            apply_inference(
                idx=idx,
                method="inferred_name_median",
                vol=stats.get("vol_mean_num"),
                spd=stats.get("spd_mean_num"),
                trvl=stats.get("trvlTime_mean_num"),
                route_name=gdf.at[idx, "name_norm"],
                rows_used=str(name_count.get(gdf.at[idx, "name_norm"], "")),
            )
        remaining -= set(name_candidates.tolist())

    observed = gdf.loc[(gdf["traffic_match_original"] == "matched") & gdf["vol_mean_num"].notna()].copy()

    # 2) Same family nearest observed segment (<= 250m).
    if remaining and not observed.empty:
        obs_geo = observed.loc[observed.geometry.notna()].copy()
        if not obs_geo.empty:
            obs_geo = obs_geo.to_crs(METRIC_CRS)
            for family in sorted(x for x in gdf.loc[list(remaining), "road_family"].dropna().unique().tolist() if x):
                left = gdf.loc[list(remaining)].copy()
                left = left[(left["road_family"] == family) & left.geometry.notna()]
                if left.empty:
                    continue
                right = obs_geo[obs_geo["road_family"] == family]
                if right.empty:
                    continue

                left_m = left.to_crs(METRIC_CRS)
                joined = gpd.sjoin_nearest(
                    left_m,
                    right[
                        [
                            "vol_mean_num",
                            "spd_mean_num",
                            "trvlTime_mean_num",
                            "matched_route_name_norm",
                            "matched_route_no",
                            "traffic_rows_used",
                            "geometry",
                        ]
                    ],
                    how="left",
                    distance_col="inferred_distance_m",
                    max_distance=MAX_NEAREST_DISTANCE_M,
                )
                if joined.empty:
                    continue

                joined = joined.sort_values("inferred_distance_m").groupby(joined.index).first()
                vol_col = "vol_mean_num_right" if "vol_mean_num_right" in joined.columns else "vol_mean_num"
                spd_col = "spd_mean_num_right" if "spd_mean_num_right" in joined.columns else "spd_mean_num"
                trvl_col = "trvlTime_mean_num_right" if "trvlTime_mean_num_right" in joined.columns else "trvlTime_mean_num"
                name_col = (
                    "matched_route_name_norm_right"
                    if "matched_route_name_norm_right" in joined.columns
                    else "matched_route_name_norm"
                )
                no_col = "matched_route_no_right" if "matched_route_no_right" in joined.columns else "matched_route_no"
                rows_col = "traffic_rows_used_right" if "traffic_rows_used_right" in joined.columns else "traffic_rows_used"

                assigned = set()
                for idx, row in joined.iterrows():
                    if pd.isna(row.get(vol_col)):
                        continue
                    apply_inference(
                        idx=idx,
                        method="inferred_nearest_family",
                        vol=row.get(vol_col),
                        spd=row.get(spd_col),
                        trvl=row.get(trvl_col),
                        route_name=str(row.get(name_col, "")),
                        route_no=str(row.get(no_col, "")),
                        rows_used=str(row.get(rows_col, "")),
                        distance_m=row.get("inferred_distance_m"),
                    )
                    assigned.add(idx)
                remaining -= assigned

    observed = gdf.loc[(gdf["traffic_match_original"] == "matched") & gdf["vol_mean_num"].notna()].copy()

    # 3) Highway median fallback.
    if remaining and not observed.empty:
        highway_stats = observed.groupby("highway")[["vol_mean_num", "spd_mean_num", "trvlTime_mean_num"]].median()
        highway_count = observed.groupby("highway").size().to_dict()
        assigned = set()
        for idx in list(remaining):
            highway = gdf.at[idx, "highway"]
            if highway not in highway_stats.index:
                continue
            row = highway_stats.loc[highway]
            apply_inference(
                idx=idx,
                method="inferred_highway_median",
                vol=row.get("vol_mean_num"),
                spd=row.get("spd_mean_num"),
                trvl=row.get("trvlTime_mean_num"),
                rows_used=str(highway_count.get(highway, "")),
            )
            assigned.add(idx)
        remaining -= assigned

    # 4) Family median fallback.
    if remaining and not observed.empty:
        family_stats = observed.groupby("road_family")[["vol_mean_num", "spd_mean_num", "trvlTime_mean_num"]].median()
        family_count = observed.groupby("road_family").size().to_dict()
        assigned = set()
        for idx in list(remaining):
            family = gdf.at[idx, "road_family"]
            if family not in family_stats.index:
                continue
            row = family_stats.loc[family]
            apply_inference(
                idx=idx,
                method="inferred_family_median",
                vol=row.get("vol_mean_num"),
                spd=row.get("spd_mean_num"),
                trvl=row.get("trvlTime_mean_num"),
                rows_used=str(family_count.get(family, "")),
            )
            assigned.add(idx)
        remaining -= assigned

    # 5) Global median fallback.
    if remaining and not observed.empty:
        global_vol = observed["vol_mean_num"].median()
        global_spd = observed["spd_mean_num"].median()
        global_trvl = observed["trvlTime_mean_num"].median()
        for idx in list(remaining):
            apply_inference(
                idx=idx,
                method="inferred_global_median",
                vol=global_vol,
                spd=global_spd,
                trvl=global_trvl,
                rows_used=str(len(observed)),
            )
        remaining.clear()

    for col in ["vol_mean", "vol_min", "vol_max", "spd_mean", "trvlTime_mean"]:
        gdf[col] = gdf[f"{col}_num"].map(format_num)
    gdf["inferred_distance_m"] = gdf["inferred_distance_m"].map(lambda v: format_num(v, digits=2))

    output_columns = list(original_columns)
    output_columns.extend(["traffic_match_original", "traffic_observed_match", "traffic_inferred", "inferred_distance_m"])

    out_df = gdf[output_columns].copy()
    out_df.to_csv(OUT_MERGED_CSV, index=False, encoding="utf-8")

    attrs_by_way = {}
    for rec in out_df.to_dict(orient="records"):
        way_id = str(rec.get("way_id", "")).strip()
        if not way_id:
            continue
        clean = {}
        for k, v in rec.items():
            if pd.isna(v):
                clean[k] = ""
            elif isinstance(v, (np.integer, np.floating)):
                clean[k] = v.item()
            else:
                clean[k] = v
        attrs_by_way[way_id] = clean

    full_info = update_geojson_properties(IN_LINES_FULL, OUT_LINES_FULL, attrs_by_way)
    boundary_info = update_geojson_properties(IN_LINES_BOUNDARY, OUT_LINES_BOUNDARY, attrs_by_way)

    observed_count = int((out_df["traffic_observed_match"] == "yes").sum())
    inferred_count = int((out_df["traffic_inferred"] == "yes").sum())
    total_count = int(len(out_df))

    drivable_mask = out_df["highway"].isin(DRIVABLE_HIGHWAYS)
    drivable_total = int(drivable_mask.sum())
    drivable_observed = int(((out_df["traffic_observed_match"] == "yes") & drivable_mask).sum())
    drivable_inferred = int(((out_df["traffic_inferred"] == "yes") & drivable_mask).sum())

    boundary_way_ids = set(boundary_info["way_ids"])
    boundary_df = out_df[out_df["way_id"].astype(str).isin(boundary_way_ids)]
    boundary_observed = int((boundary_df["traffic_observed_match"] == "yes").sum())
    boundary_inferred = int((boundary_df["traffic_inferred"] == "yes").sum())

    coverage = {
        "source": "spatial/statistical inference on top of uiwang_all_roads_with_traffic",
        "parameters": {
            "nearest_family_max_distance_m": MAX_NEAREST_DISTANCE_M,
            "drivable_highways": sorted(DRIVABLE_HIGHWAYS),
        },
        "full": {
            "segment_total": total_count,
            "observed_match_count": observed_count,
            "observed_match_rate_pct": round((observed_count / total_count) * 100.0, 2),
            "inferred_count": inferred_count,
            "remaining_no_match_count": total_count - observed_count - inferred_count,
            "effective_coverage_pct": round(((observed_count + inferred_count) / total_count) * 100.0, 2),
        },
        "drivable": {
            "segment_total": drivable_total,
            "observed_match_count": drivable_observed,
            "observed_match_rate_pct": round((drivable_observed / drivable_total) * 100.0, 2)
            if drivable_total
            else 0.0,
            "inferred_count": drivable_inferred,
            "effective_coverage_pct": round(((drivable_observed + drivable_inferred) / drivable_total) * 100.0, 2)
            if drivable_total
            else 0.0,
        },
        "boundary_subset": {
            "segment_total": int(len(boundary_df)),
            "observed_match_count": boundary_observed,
            "inferred_count": boundary_inferred,
            "effective_coverage_pct": round(((boundary_observed + boundary_inferred) / len(boundary_df)) * 100.0, 2)
            if len(boundary_df)
            else 0.0,
        },
        "method_breakdown": dict(method_counts),
        "outputs": {
            "merged_csv": OUT_MERGED_CSV.name,
            "lines_full_geojson": OUT_LINES_FULL.name,
            "lines_boundary_geojson": OUT_LINES_BOUNDARY.name,
            "coverage_json": OUT_COVERAGE_JSON.name,
            "full_geojson_update": {
                "feature_count": full_info["feature_count"],
                "updated_count": full_info["updated_count"],
            },
            "boundary_geojson_update": {
                "feature_count": boundary_info["feature_count"],
                "updated_count": boundary_info["updated_count"],
            },
        },
    }
    OUT_COVERAGE_JSON.write_text(json.dumps(coverage, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(coverage, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()