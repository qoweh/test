#!/usr/bin/env python3
import csv
import json
import re
from pathlib import Path
from statistics import mean


ROOT = Path(__file__).resolve().parent.parent
PLUS = ROOT / "plus"

OSM_SEGMENTS_CSV = PLUS / "uiwang_osm_roads_segments.csv"
OSM_NAMED_CSV = PLUS / "uiwang_osm_named_roads_summary.csv"
GG_ROAD_INFO_CSV = PLUS / "gg_road_info_list.csv"
GG_TRAFFIC_CSV = PLUS / "gg_road_traffic_info_list.csv"
ROAD_VALIDATION_CSV = PLUS / "uiwang_road_boundary_validation.csv"

OUT_SEGMENTS_MERGED_CSV = PLUS / "uiwang_all_roads_with_traffic.csv"
OUT_NAMED_MERGED_CSV = PLUS / "uiwang_named_roads_with_traffic_summary.csv"
OUT_GG_ROUTE_STATS_CSV = PLUS / "uiwang_gg_route_traffic_stats.csv"
OUT_GG_ROUTE_NO_STATS_CSV = PLUS / "uiwang_gg_routeno_traffic_stats.csv"
OUT_COVERAGE_JSON = PLUS / "uiwang_traffic_data_coverage.json"


UIWANG_KEYWORDS = [
    "의왕",
    "고천",
    "오전",
    "내손",
    "포일",
    "청계",
    "부곡",
    "월암",
    "왕곡",
    "학의",
    "초평",
    "백운",
]


def normalize_name(name: str) -> str:
    if not name:
        return ""
    name = re.sub(r"\s+", "", name)
    return name.strip()


def split_route_aliases(name: str):
    norm = normalize_name(name)
    if not norm:
        return []

    # Remove parenthesized annotations and split common composite delimiters.
    norm = re.sub(r"\([^)]*\)", "", norm)
    parts = re.split(r"[/·,]|→|↔|-", norm)

    aliases = []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        p = re.sub(r"(구간|일원|방면)$", "", p)
        if p:
            aliases.append(p)

    seen = set()
    uniq = []
    for a in aliases:
        if a in seen:
            continue
        seen.add(a)
        uniq.append(a)
    return uniq


def extract_numbers(text: str):
    if not text:
        return []
    return re.findall(r"\d+", text)


def to_float(value):
    if value is None:
        return None
    v = str(value).strip()
    if not v:
        return None
    try:
        return float(v)
    except ValueError:
        return None


def stat_dict(values):
    if not values:
        return {
            "mean": "",
            "min": "",
            "max": "",
        }
    return {
        "mean": round(mean(values), 3),
        "min": round(min(values), 3),
        "max": round(max(values), 3),
    }


def append_numeric_values(acc: dict, row: dict):
    vol = to_float(row.get("vol"))
    spd = to_float(row.get("spd"))
    trvl = to_float(row.get("trvlTime"))
    if vol is not None:
        acc["vol_values"].append(vol)
    if spd is not None:
        acc["spd_values"].append(spd)
    if trvl is not None:
        acc["trvl_values"].append(trvl)


def best_route_no_match(route_numbers, route_no_stats_by_no):
    candidates = [route_no_stats_by_no[r] for r in route_numbers if r in route_no_stats_by_no]
    if not candidates:
        return None
    return sorted(candidates, key=lambda x: (-int(x["row_count"]), x["route_no"]))[0]


def main():
    if not OSM_SEGMENTS_CSV.exists():
        raise FileNotFoundError(f"Missing required file: {OSM_SEGMENTS_CSV}")
    if not OSM_NAMED_CSV.exists():
        raise FileNotFoundError(f"Missing required file: {OSM_NAMED_CSV}")
    if not GG_ROAD_INFO_CSV.exists():
        raise FileNotFoundError(f"Missing required file: {GG_ROAD_INFO_CSV}")
    if not GG_TRAFFIC_CSV.exists():
        raise FileNotFoundError(f"Missing required file: {GG_TRAFFIC_CSV}")

    with OSM_NAMED_CSV.open("r", encoding="utf-8", newline="") as f:
        osm_named_rows = list(csv.DictReader(f))

    osm_norm_names = set()
    for row in osm_named_rows:
        n = normalize_name(row.get("road_name", ""))
        if n:
            osm_norm_names.add(n)

    with OSM_SEGMENTS_CSV.open("r", encoding="utf-8", newline="") as f:
        osm_segment_rows = list(csv.DictReader(f))

    validation_by_way_id = {}
    if ROAD_VALIDATION_CSV.exists():
        with ROAD_VALIDATION_CSV.open("r", encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                wid = str(row.get("way_id", "")).strip()
                if wid:
                    validation_by_way_id[wid] = row

    with GG_ROAD_INFO_CSV.open("r", encoding="utf-8", newline="") as f:
        gg_road_info_rows = list(csv.DictReader(f))

    route_id_to_no = {}
    for row in gg_road_info_rows:
        route_id = (row.get("routeId") or "").strip()
        route_no_nums = extract_numbers(row.get("routeNo", ""))
        if route_id and route_no_nums:
            route_id_to_no[route_id] = route_no_nums[0]

    osm_ref_numbers = set()
    name_to_ref_numbers = {}
    for row in osm_segment_rows:
        nums = set(extract_numbers(row.get("ref", "")))
        if nums:
            osm_ref_numbers.update(nums)
            road_name = (row.get("name") or "").strip()
            if road_name:
                name_to_ref_numbers.setdefault(road_name, set()).update(nums)

    route_acc = {}
    route_no_acc = {}
    gg_total_rows = 0
    gg_name_match_rows = 0
    gg_alias_match_rows = 0
    gg_keyword_rows = 0
    gg_ref_match_rows = 0

    with GG_TRAFFIC_CSV.open("r", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            gg_total_rows += 1
            route_nm = (row.get("routeNm") or "").strip()
            route_norm = normalize_name(route_nm)
            if not route_norm:
                continue

            combined_text = " ".join(
                [
                    row.get("routeNm", ""),
                    row.get("startNodeNm", ""),
                    row.get("endNodeNm", ""),
                ]
            )
            keyword_hit = any(k in combined_text for k in UIWANG_KEYWORDS)
            name_match = route_norm in osm_norm_names
            alias_match = any(a in osm_norm_names for a in split_route_aliases(route_nm))

            if name_match:
                gg_name_match_rows += 1
            if alias_match:
                gg_alias_match_rows += 1
            if keyword_hit:
                gg_keyword_rows += 1

            route_id = (row.get("routeId") or row.get("routeId_query") or "").strip()
            route_no = route_id_to_no.get(route_id, "")
            ref_match = route_no in osm_ref_numbers
            if ref_match:
                gg_ref_match_rows += 1

            if route_norm not in route_acc:
                route_acc[route_norm] = {
                    "route_name_samples": set(),
                    "rows": 0,
                    "name_match_rows": 0,
                    "alias_match_rows": 0,
                    "keyword_rows": 0,
                    "vol_values": [],
                    "spd_values": [],
                    "trvl_values": [],
                }

            acc = route_acc[route_norm]
            acc["route_name_samples"].add(route_nm)
            acc["rows"] += 1
            if name_match:
                acc["name_match_rows"] += 1
            if alias_match:
                acc["alias_match_rows"] += 1
            if keyword_hit:
                acc["keyword_rows"] += 1

            append_numeric_values(acc, row)

            if ref_match:
                if route_no not in route_no_acc:
                    route_no_acc[route_no] = {
                        "route_name_samples": set(),
                        "rows": 0,
                        "vol_values": [],
                        "spd_values": [],
                        "trvl_values": [],
                    }
                no_acc = route_no_acc[route_no]
                no_acc["route_name_samples"].add(route_nm)
                no_acc["rows"] += 1
                append_numeric_values(no_acc, row)

    route_stats_rows = []
    route_stats_by_norm = {}

    for route_norm, acc in route_acc.items():
        if acc["name_match_rows"] <= 0 and acc["alias_match_rows"] <= 0 and acc["keyword_rows"] <= 0:
            continue

        vol_stats = stat_dict(acc["vol_values"])
        spd_stats = stat_dict(acc["spd_values"])
        trvl_stats = stat_dict(acc["trvl_values"])

        if acc["name_match_rows"] > 0:
            reason = "route_name_match"
        elif acc["alias_match_rows"] > 0:
            reason = "route_name_alias_match"
        else:
            reason = "uiwang_keyword_match"

        row = {
            "route_name_norm": route_norm,
            "route_name_samples": " | ".join(sorted(x for x in acc["route_name_samples"] if x)),
            "selection_reason": reason,
            "row_count": acc["rows"],
            "name_match_rows": acc["name_match_rows"],
            "alias_match_rows": acc["alias_match_rows"],
            "keyword_rows": acc["keyword_rows"],
            "vol_mean": vol_stats["mean"],
            "vol_min": vol_stats["min"],
            "vol_max": vol_stats["max"],
            "spd_mean": spd_stats["mean"],
            "spd_min": spd_stats["min"],
            "spd_max": spd_stats["max"],
            "trvlTime_mean": trvl_stats["mean"],
            "trvlTime_min": trvl_stats["min"],
            "trvlTime_max": trvl_stats["max"],
        }
        route_stats_rows.append(row)

        if reason == "route_name_match":
            route_stats_by_norm[route_norm] = row

    route_stats_rows.sort(key=lambda r: (r["selection_reason"], -int(r["row_count"])))

    route_stats_by_alias = {}
    for row in route_stats_rows:
        names = [row.get("route_name_norm", "")]
        sample = row.get("route_name_samples", "")
        if sample:
            names.extend(sample.split(" | "))

        aliases = set()
        for n in names:
            for a in split_route_aliases(n):
                aliases.add(a)

        for alias in aliases:
            prev = route_stats_by_alias.get(alias)
            if prev is None or int(row.get("row_count", 0)) > int(prev.get("row_count", 0)):
                route_stats_by_alias[alias] = row

    with OUT_GG_ROUTE_STATS_CSV.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "route_name_norm",
                "route_name_samples",
                "selection_reason",
                "row_count",
                "name_match_rows",
                "alias_match_rows",
                "keyword_rows",
                "vol_mean",
                "vol_min",
                "vol_max",
                "spd_mean",
                "spd_min",
                "spd_max",
                "trvlTime_mean",
                "trvlTime_min",
                "trvlTime_max",
            ],
        )
        writer.writeheader()
        writer.writerows(route_stats_rows)

    route_no_stats_rows = []
    route_no_stats_by_no = {}
    for route_no, acc in sorted(route_no_acc.items(), key=lambda kv: -kv[1]["rows"]):
        vol_stats = stat_dict(acc["vol_values"])
        spd_stats = stat_dict(acc["spd_values"])
        trvl_stats = stat_dict(acc["trvl_values"])

        row = {
            "route_no": route_no,
            "route_name_samples": " | ".join(sorted(x for x in acc["route_name_samples"] if x)),
            "selection_reason": "route_no_ref_match",
            "row_count": acc["rows"],
            "vol_mean": vol_stats["mean"],
            "vol_min": vol_stats["min"],
            "vol_max": vol_stats["max"],
            "spd_mean": spd_stats["mean"],
            "spd_min": spd_stats["min"],
            "spd_max": spd_stats["max"],
            "trvlTime_mean": trvl_stats["mean"],
            "trvlTime_min": trvl_stats["min"],
            "trvlTime_max": trvl_stats["max"],
        }
        route_no_stats_rows.append(row)
        route_no_stats_by_no[route_no] = row

    with OUT_GG_ROUTE_NO_STATS_CSV.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "route_no",
                "route_name_samples",
                "selection_reason",
                "row_count",
                "vol_mean",
                "vol_min",
                "vol_max",
                "spd_mean",
                "spd_min",
                "spd_max",
                "trvlTime_mean",
                "trvlTime_min",
                "trvlTime_max",
            ],
        )
        writer.writeheader()
        writer.writerows(route_no_stats_rows)

    named_out = []
    matched_named_count = 0
    matched_named_by_name = 0
    matched_named_by_ref = 0
    matched_named_by_alias = 0

    for row in osm_named_rows:
        road_name = row.get("road_name", "")
        highway = row.get("highway", "")
        norm = normalize_name(road_name)
        traffic_name = route_stats_by_norm.get(norm)
        traffic_alias = route_stats_by_alias.get(norm)
        ref_numbers = sorted(name_to_ref_numbers.get(road_name, set()))
        traffic_ref = best_route_no_match(ref_numbers, route_no_stats_by_no)

        traffic = None
        match_method = "no_match"
        matched_route_no = ""
        matched_route_name_norm = ""
        if traffic_name is not None:
            traffic = traffic_name
            match_method = "route_name_match"
            matched_route_name_norm = traffic_name.get("route_name_norm", "")
            matched_named_by_name += 1
        elif traffic_ref is not None:
            traffic = traffic_ref
            match_method = "route_no_ref_match"
            matched_route_no = traffic_ref.get("route_no", "")
            matched_named_by_ref += 1
        elif traffic_alias is not None:
            traffic = traffic_alias
            match_method = "route_name_alias_match"
            matched_route_name_norm = traffic_alias.get("route_name_norm", "")
            matched_named_by_alias += 1

        is_matched = traffic is not None

        if is_matched:
            matched_named_count += 1

        named_out.append(
            {
                "road_name": road_name,
                "highway": highway,
                "segment_count": row.get("segment_count", ""),
                "total_length_m": row.get("total_length_m", ""),
                "total_length_km": row.get("total_length_km", ""),
                "traffic_match": "matched" if is_matched else "no_match",
                "traffic_match_method": match_method,
                "matched_route_name_norm": matched_route_name_norm,
                "matched_route_no": matched_route_no,
                "vol_mean": "" if not is_matched else traffic.get("vol_mean", ""),
                "vol_min": "" if not is_matched else traffic.get("vol_min", ""),
                "vol_max": "" if not is_matched else traffic.get("vol_max", ""),
                "spd_mean": "" if not is_matched else traffic.get("spd_mean", ""),
                "trvlTime_mean": "" if not is_matched else traffic.get("trvlTime_mean", ""),
                "traffic_rows_used": "" if not is_matched else traffic.get("row_count", ""),
                "source_road": "OpenStreetMap Overpass bbox query",
                "source_traffic": "Gyeonggi OpenAPI getRoadTrafficInfoList + getRoadInfoList(routeNo mapping)",
            }
        )

    named_out.sort(
        key=lambda r: (
            0 if r["traffic_match"] == "matched" else 1,
            -float(r["total_length_m"] or 0),
        )
    )

    with OUT_NAMED_MERGED_CSV.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "road_name",
                "highway",
                "segment_count",
                "total_length_m",
                "total_length_km",
                "traffic_match",
                "traffic_match_method",
                "matched_route_name_norm",
                "matched_route_no",
                "vol_mean",
                "vol_min",
                "vol_max",
                "spd_mean",
                "trvlTime_mean",
                "traffic_rows_used",
                "source_road",
                "source_traffic",
            ],
        )
        writer.writeheader()
        writer.writerows(named_out)

    segments_out = []
    matched_segment_count = 0
    matched_segment_by_name = 0
    matched_segment_by_ref = 0
    matched_segment_by_alias = 0
    named_segment_count = 0

    for row in osm_segment_rows:
        road_name = row.get("name", "")
        norm = normalize_name(road_name)
        traffic_name = route_stats_by_norm.get(norm) if norm else None
        traffic_alias = route_stats_by_alias.get(norm) if norm else None

        way_id = str(row.get("way_id", "")).strip()
        valid = validation_by_way_id.get(way_id, {})

        ref_numbers = extract_numbers(row.get("ref", ""))
        traffic_ref = best_route_no_match(ref_numbers, route_no_stats_by_no)

        traffic = None
        match_method = "no_match"
        matched_route_no = ""
        matched_route_name_norm = ""
        if traffic_name is not None:
            traffic = traffic_name
            match_method = "route_name_match"
            matched_route_name_norm = traffic_name.get("route_name_norm", "")
            matched_segment_by_name += 1
        elif traffic_ref is not None:
            traffic = traffic_ref
            match_method = "route_no_ref_match"
            matched_route_no = traffic_ref.get("route_no", "")
            matched_segment_by_ref += 1
        elif traffic_alias is not None:
            traffic = traffic_alias
            match_method = "route_name_alias_match"
            matched_route_name_norm = traffic_alias.get("route_name_norm", "")
            matched_segment_by_alias += 1

        if road_name:
            named_segment_count += 1
        if traffic is not None:
            matched_segment_count += 1

        out_row = dict(row)
        out_row.update(
            {
                "traffic_match": "matched" if traffic is not None else "no_match",
                "traffic_match_method": match_method,
                "matched_route_name_norm": matched_route_name_norm,
                "matched_route_no": matched_route_no,
                "vol_mean": "" if traffic is None else traffic.get("vol_mean", ""),
                "vol_min": "" if traffic is None else traffic.get("vol_min", ""),
                "vol_max": "" if traffic is None else traffic.get("vol_max", ""),
                "spd_mean": "" if traffic is None else traffic.get("spd_mean", ""),
                "trvlTime_mean": "" if traffic is None else traffic.get("trvlTime_mean", ""),
                "traffic_rows_used": "" if traffic is None else traffic.get("row_count", ""),
                "boundary_validation_status": valid.get("validation_status", ""),
                "boundary_inside_vertex_count": valid.get("inside_vertex_count", ""),
                "boundary_outside_vertex_count": valid.get("outside_vertex_count", ""),
                "boundary_intersects": valid.get("intersects_boundary", ""),
                "source_road": "OpenStreetMap Overpass bbox query",
                "source_traffic": "Gyeonggi OpenAPI getRoadTrafficInfoList + getRoadInfoList(routeNo mapping)",
            }
        )
        segments_out.append(out_row)

    with OUT_SEGMENTS_MERGED_CSV.open("w", encoding="utf-8", newline="") as f:
        fieldnames = list(segments_out[0].keys()) if segments_out else []
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(segments_out)

    coverage = {
        "sources": {
            "road_inventory": {
                "name": "OpenStreetMap Overpass",
                "query_basis": "Uiwang boundary bbox highway ways",
            },
            "traffic": {
                "name": "Gyeonggi OpenAPI",
                "endpoint": "https://openapigits.gg.go.kr/api/rest/getRoadTrafficInfoList",
                "route_info_endpoint": "https://openapigits.gg.go.kr/api/rest/getRoadInfoList",
            },
        },
        "counts": {
            "osm_segment_total": len(osm_segment_rows),
            "osm_named_segment_total": named_segment_count,
            "osm_named_road_total": len(osm_named_rows),
            "gg_traffic_row_total": gg_total_rows,
            "gg_name_match_row_total": gg_name_match_rows,
            "gg_alias_match_row_total": gg_alias_match_rows,
            "gg_keyword_row_total": gg_keyword_rows,
            "gg_ref_match_row_total": gg_ref_match_rows,
            "matched_named_road_count": matched_named_count,
            "matched_named_road_by_name_count": matched_named_by_name,
            "matched_named_road_by_ref_count": matched_named_by_ref,
            "matched_named_road_by_alias_count": matched_named_by_alias,
            "unmatched_named_road_count": len(osm_named_rows) - matched_named_count,
            "matched_segment_count": matched_segment_count,
            "matched_segment_by_name_count": matched_segment_by_name,
            "matched_segment_by_ref_count": matched_segment_by_ref,
            "matched_segment_by_alias_count": matched_segment_by_alias,
            "unmatched_segment_count": len(osm_segment_rows) - matched_segment_count,
        },
    }

    OUT_COVERAGE_JSON.write_text(json.dumps(coverage, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(coverage, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
