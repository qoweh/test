#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
import re
from collections import defaultdict
from pathlib import Path
from statistics import mean
from xml.etree import ElementTree as ET

import requests
import urllib3


urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

ROOT = Path(__file__).resolve().parent.parent
PLUS = ROOT / "plus"

IN_MERGED_CSV = PLUS / "uiwang_all_roads_with_traffic.csv"
IN_LINES_GEOJSON = PLUS / "uiwang_osm_roads_filtered.geojson"

OUT_ROADRE_STATS_CSV = PLUS / "roadre_uiwang_route_stats.csv"
OUT_SPOTS_CSV = PLUS / "roadre_uiwang_spots_selected.csv"
OUT_MERGED_RETRY_CSV = PLUS / "uiwang_all_roads_with_traffic_roadre_retry.csv"
OUT_LINES_RETRY_GEOJSON = PLUS / "uiwang_all_roads_with_traffic_lines_roadre_retry.geojson"
OUT_COVERAGE_RETRY_JSON = PLUS / "uiwang_traffic_data_coverage_roadre_retry.json"

ROADRE_BASE = "https://www.road.re.kr/itms"
UIWANG_KEYWORDS = [
    "의왕",
    "안양",
    "과천",
    "군포",
    "판교",
    "청계",
    "내손",
    "오전",
    "포일",
    "부곡",
    "학의",
    "고천",
    "평촌",
    "금토",
]


def fetch_xml(session: requests.Session, url: str) -> ET.Element:
    resp = session.get(url, verify=False, timeout=90)
    resp.raise_for_status()
    txt = resp.content.decode("cp949", "replace")
    txt = txt.replace("<?xml version='1.0' encoding='euc-kr'?>", "", 1)
    return ET.fromstring(txt)


def parse_rows(root: ET.Element) -> list[list[str]]:
    out: list[list[str]] = []
    for row in root.findall("row"):
        cells = [(c.text or "").strip() for c in row.findall("cell")]
        if cells:
            out.append(cells)
    return out


def chunk(values: list[str], size: int):
    for i in range(0, len(values), size):
        yield values[i : i + size]


def extract_route_tokens(text: str) -> list[str]:
    return re.findall(r"\d+", text or "")


def to_float(v: str):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def stat(values: list[float]) -> dict[str, str]:
    if not values:
        return {"mean": "", "min": "", "max": ""}
    return {
        "mean": round(mean(values), 3),
        "min": round(min(values), 3),
        "max": round(max(values), 3),
    }


def main() -> None:
    if not IN_MERGED_CSV.exists():
        raise FileNotFoundError(IN_MERGED_CSV)
    if not IN_LINES_GEOJSON.exists():
        raise FileNotFoundError(IN_LINES_GEOJSON)

    with IN_MERGED_CSV.open("r", encoding="utf-8", newline="") as f:
        merged_rows = list(csv.DictReader(f))

    osm_ref_numbers = set()
    for row in merged_rows:
        osm_ref_numbers.update(extract_route_tokens(row.get("ref", "")))

    session = requests.Session()

    # 1) Road list (data=3, year=2024)
    road_url = f"{ROADRE_BASE}/itms_22_search.asp?mode=road&data=3&year=2024&grade=1,2,3,5"
    road_rows = parse_rows(fetch_xml(session, road_url))

    roads = []
    by_level: dict[int, list[str]] = defaultdict(list)
    for c in road_rows:
        if len(c) < 6:
            continue
        road_name = c[2]
        road_level = c[4]
        line_id = c[5]
        roads.append(
            {
                "road_name": road_name,
                "road_level": road_level,
                "line_id": line_id,
            }
        )
        try:
            lv = int(float(road_level))
            by_level[lv].append(line_id)
        except (TypeError, ValueError):
            continue

    # 2) Spot list
    spots = []
    for lv in [1, 2, 3, 4, 5]:
        ids = by_level.get(lv, [])
        if not ids:
            continue
        for part in chunk(ids, 45):
            params = {
                "road1_ids": "",
                "road2_ids": "",
                "road3_ids": "",
                "road4_ids": "",
                "road5_ids": "",
            }
            params[f"road{lv}_ids"] = ",".join(part)
            qs = "&".join(f"{k}={v}" for k, v in params.items())
            u = f"{ROADRE_BASE}/itms_22_search.asp?mode=spot&data=3&year=2024&{qs}"
            rows = parse_rows(fetch_xml(session, u))
            for c in rows:
                if len(c) < 7:
                    continue
                spot = {
                    "road_name": c[2],
                    "section": c[3],
                    "road_level": c[4],
                    "line_id": c[5],
                    "spot_id": c[6],
                }
                spots.append(spot)

    # 3) Uiwang-relevant spot filtering
    selected_spots = []
    selected_spot_ids = []
    for s in spots:
        text = f"{s['road_name']} {s['section']}"
        route_tokens = extract_route_tokens(s.get("line_id", ""))
        by_keyword = any(k in text for k in UIWANG_KEYWORDS)
        by_ref_overlap = any(t in osm_ref_numbers for t in route_tokens)
        if by_keyword or by_ref_overlap:
            selected_spots.append(s)
            selected_spot_ids.append(s["spot_id"])

    selected_spot_ids = sorted(set(selected_spot_ids))

    with OUT_SPOTS_CSV.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["road_name", "section", "road_level", "line_id", "spot_id"],
        )
        writer.writeheader()
        writer.writerows(selected_spots)

    spot_meta = {s["spot_id"]: s for s in selected_spots}

    # 4) Fetch data rows and aggregate by route token
    route_acc: dict[str, dict] = {}

    for part in chunk(selected_spot_ids, 90):
        spot_q = ",".join(part)
        data_url = f"{ROADRE_BASE}/itms_22_data.asp?data=3&year=2024&spot={spot_q}"
        rows = parse_rows(fetch_xml(session, data_url))
        for c in rows:
            if len(c) < 24:
                continue
            road_name = c[1]
            spot_id = c[2]
            total = to_float(c[22])
            if total is None:
                continue

            meta = spot_meta.get(spot_id)
            if meta is None:
                continue

            tokens = extract_route_tokens(meta.get("line_id", ""))
            if not tokens:
                continue
            route_token = tokens[0]

            if route_token not in route_acc:
                route_acc[route_token] = {
                    "route_token": route_token,
                    "line_ids": set(),
                    "road_names": set(),
                    "sections": set(),
                    "spot_ids": set(),
                    "vol_values": [],
                }

            acc = route_acc[route_token]
            acc["line_ids"].add(meta.get("line_id", ""))
            if road_name:
                acc["road_names"].add(road_name)
            if meta.get("section"):
                acc["sections"].add(meta["section"])
            acc["spot_ids"].add(spot_id)
            acc["vol_values"].append(total)

    route_stats_rows = []
    route_stats_by_token = {}
    for token, acc in sorted(route_acc.items(), key=lambda kv: int(kv[0])):
        vol_stats = stat(acc["vol_values"])
        row = {
            "route_token": token,
            "line_ids": " | ".join(sorted(x for x in acc["line_ids"] if x)),
            "road_name_samples": " | ".join(sorted(x for x in acc["road_names"] if x)),
            "section_samples": " | ".join(sorted(x for x in acc["sections"] if x)[:30]),
            "spot_count": len(acc["spot_ids"]),
            "row_count": len(acc["vol_values"]),
            "vol_mean": vol_stats["mean"],
            "vol_min": vol_stats["min"],
            "vol_max": vol_stats["max"],
            "source": "road.re.kr itms_22 (data=3)",
        }
        route_stats_rows.append(row)
        route_stats_by_token[token] = row

    with OUT_ROADRE_STATS_CSV.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "route_token",
                "line_ids",
                "road_name_samples",
                "section_samples",
                "spot_count",
                "row_count",
                "vol_mean",
                "vol_min",
                "vol_max",
                "source",
            ],
        )
        writer.writeheader()
        writer.writerows(route_stats_rows)

    # 5) Apply retry matching to previously unmatched OSM segments.
    retry_rows = []
    before_matched = 0
    after_matched = 0
    added_by_roadre = 0

    for row in merged_rows:
        out = dict(row)
        was_matched = str(row.get("traffic_match", "")) == "matched"
        if was_matched:
            before_matched += 1
            after_matched += 1
            retry_rows.append(out)
            continue

        refs = extract_route_tokens(row.get("ref", ""))
        picked = None
        for t in refs:
            if t in route_stats_by_token:
                cand = route_stats_by_token[t]
                if picked is None or int(cand["row_count"]) > int(picked["row_count"]):
                    picked = cand

        if picked is not None:
            out["traffic_match"] = "matched"
            out["traffic_match_method"] = "roadre_lineid_ref_match"
            out["matched_route_name_norm"] = (picked.get("road_name_samples") or "").split(" | ")[0]
            out["matched_route_no"] = picked.get("route_token", "")
            out["vol_mean"] = picked.get("vol_mean", "")
            out["vol_min"] = picked.get("vol_min", "")
            out["vol_max"] = picked.get("vol_max", "")
            # road.re endpoint does not expose speed/travel-time fields in this flow.
            out["spd_mean"] = out.get("spd_mean", "")
            out["trvlTime_mean"] = out.get("trvlTime_mean", "")
            out["traffic_rows_used"] = picked.get("row_count", "")
            out["source_traffic"] = "road.re.kr itms_22_data(data=3) + 기존 Gyeonggi OpenAPI"
            added_by_roadre += 1
            after_matched += 1

        retry_rows.append(out)

    with OUT_MERGED_RETRY_CSV.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(retry_rows[0].keys()))
        writer.writeheader()
        writer.writerows(retry_rows)

    # 6) Build line GeoJSON with retry attributes.
    attrs_by_way = {}
    for r in retry_rows:
        way_id = str(r.get("way_id", "")).strip()
        if way_id:
            attrs_by_way[way_id] = r

    line_data = json.loads(IN_LINES_GEOJSON.read_text(encoding="utf-8"))
    out_features = []
    for ft in line_data.get("features", []):
        props = ft.get("properties", {})
        way_id = str(props.get("way_id", "")).strip()
        merged_props = dict(props)
        if way_id in attrs_by_way:
            merged_props.update(attrs_by_way[way_id])
        out_features.append(
            {
                "type": "Feature",
                "geometry": ft.get("geometry"),
                "properties": merged_props,
            }
        )

    out_geo = {
        "type": "FeatureCollection",
        "name": "uiwang_all_roads_with_traffic_lines_roadre_retry",
        "features": out_features,
    }
    OUT_LINES_RETRY_GEOJSON.write_text(json.dumps(out_geo, ensure_ascii=False), encoding="utf-8")

    coverage = {
        "source": "road.re.kr retry on top of existing merge",
        "before": {
            "segment_total": len(merged_rows),
            "matched_segment_count": before_matched,
            "matched_segment_rate_pct": round((before_matched / len(merged_rows)) * 100.0, 2),
        },
        "after": {
            "segment_total": len(retry_rows),
            "matched_segment_count": after_matched,
            "matched_segment_rate_pct": round((after_matched / len(retry_rows)) * 100.0, 2),
            "added_by_roadre_ref_match": added_by_roadre,
        },
        "roadre_collection": {
            "road_rows": len(roads),
            "spot_rows": len(spots),
            "selected_spot_count": len(selected_spot_ids),
            "route_stats_count": len(route_stats_rows),
        },
        "output_files": {
            "roadre_route_stats_csv": OUT_ROADRE_STATS_CSV.name,
            "selected_spots_csv": OUT_SPOTS_CSV.name,
            "merged_retry_csv": OUT_MERGED_RETRY_CSV.name,
            "lines_retry_geojson": OUT_LINES_RETRY_GEOJSON.name,
        },
    }

    OUT_COVERAGE_RETRY_JSON.write_text(json.dumps(coverage, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(coverage, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
