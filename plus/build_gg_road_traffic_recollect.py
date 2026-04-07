#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path


BASE_URL = "https://openapigits.gg.go.kr/api/rest"


def request_xml(endpoint: str, params: dict, timeout: int, retries: int, backoff_sec: float) -> str:
    query = urllib.parse.urlencode(params)
    url = f"{BASE_URL}/{endpoint}?{query}"
    last_error = None

    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(url, timeout=timeout) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except Exception as exc:
            last_error = exc
            if attempt < retries:
                delay = backoff_sec * (2 ** attempt)
                time.sleep(delay)

    raise last_error


def parse_header(xml_text: str) -> dict:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return {"headerCd": None, "headerMsg": "XML parse error", "itemCount": None}

    return {
        "headerCd": root.findtext(".//headerCd"),
        "headerMsg": root.findtext(".//headerMsg"),
        "itemCount": root.findtext(".//itemCount"),
    }


def _element_to_dict(el: ET.Element) -> dict:
    out = {}
    for c in list(el):
        out[c.tag] = (c.text or "").strip()
    return out


def extract_record_list(xml_text: str) -> list[dict]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []

    item_lists = root.findall(".//itemList")
    records = []
    for node in item_lists:
        children = list(node)
        if children:
            for c in children:
                d = _element_to_dict(c)
                if d:
                    records.append(d)
        else:
            d = _element_to_dict(node)
            if d:
                records.append(d)

    return records


def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return

    fieldnames = sorted({k for row in rows for k in row.keys()})
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def read_route_ids(path: Path) -> list[str]:
    with path.open("r", newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    route_ids = []
    seen = set()
    for row in rows:
        rid = (row.get("routeId") or "").strip()
        if rid and rid not in seen:
            route_ids.append(rid)
            seen.add(rid)
    return route_ids


def row_key(row: dict) -> tuple:
    cleaned = tuple(sorted((k, str(v).strip()) for k, v in row.items()))
    return cleaned


def merge_dedup_rows(base_rows: list[dict], new_rows: list[dict]) -> list[dict]:
    out = []
    seen = set()

    for row in base_rows + new_rows:
        key = row_key(row)
        if key in seen:
            continue
        seen.add(key)
        out.append(row)

    return out


def fetch_road_info_csv(service_key: str, route_csv: Path, timeout: int, retries: int, backoff_sec: float) -> dict:
    xml_text = request_xml(
        "getRoadInfoList",
        {"serviceKey": service_key},
        timeout=timeout,
        retries=retries,
        backoff_sec=backoff_sec,
    )
    header = parse_header(xml_text)
    rows = extract_record_list(xml_text)
    write_csv(route_csv, rows)
    return {
        "header": header,
        "count": len(rows),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Re-collect GG road traffic rows with retry and merge")
    parser.add_argument("--service-key", required=True, help="OpenAPIGITS service key")
    parser.add_argument("--route-csv", default="plus/gg_road_info_list.csv", help="Route list CSV path")
    parser.add_argument(
        "--base-traffic-csv",
        default="plus/gg_road_traffic_info_list.csv",
        help="Base traffic CSV to merge with recollected rows",
    )
    parser.add_argument(
        "--out-csv",
        default="plus/gg_road_traffic_info_list_recollected.csv",
        help="Output CSV path",
    )
    parser.add_argument(
        "--failure-csv",
        default="plus/gg_road_traffic_recollect_failures.csv",
        help="Failed route log CSV path",
    )
    parser.add_argument(
        "--summary-json",
        default="plus/gg_road_traffic_recollect_summary.json",
        help="Summary JSON path",
    )
    parser.add_argument("--max-routes", type=int, default=0, help="Limit number of routes (0 = all)")
    parser.add_argument("--request-timeout", type=int, default=30, help="HTTP timeout seconds")
    parser.add_argument("--retries", type=int, default=2, help="Retries per route request")
    parser.add_argument("--backoff-sec", type=float, default=0.7, help="Retry backoff base seconds")
    parser.add_argument(
        "--sleep-per-route",
        type=float,
        default=0.05,
        help="Sleep seconds between route requests",
    )
    parser.add_argument(
        "--refresh-route-list",
        action="store_true",
        help="Force refresh getRoadInfoList before traffic recollection",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    route_csv = Path(args.route_csv)
    base_traffic_csv = Path(args.base_traffic_csv)
    out_csv = Path(args.out_csv)
    failure_csv = Path(args.failure_csv)
    summary_json = Path(args.summary_json)

    for p in [route_csv.parent, out_csv.parent, failure_csv.parent, summary_json.parent]:
        p.mkdir(parents=True, exist_ok=True)

    summary = {
        "service": "openapigits.gg.go.kr",
        "mode": "traffic_recollect",
        "parameters": {
            "request_timeout_sec": args.request_timeout,
            "retries": args.retries,
            "backoff_sec": args.backoff_sec,
            "sleep_per_route": args.sleep_per_route,
            "max_routes": args.max_routes,
            "refresh_route_list": bool(args.refresh_route_list),
        },
    }

    try:
        refreshed = False
        if args.refresh_route_list or not route_csv.exists():
            info = fetch_road_info_csv(
                service_key=args.service_key,
                route_csv=route_csv,
                timeout=args.request_timeout,
                retries=args.retries,
                backoff_sec=args.backoff_sec,
            )
            summary["route_info_refresh"] = info
            refreshed = True

        route_ids = read_route_ids(route_csv)
        if args.max_routes and args.max_routes > 0:
            route_ids = route_ids[: args.max_routes]

        recollected_rows = []
        failures = []

        for idx, rid in enumerate(route_ids, start=1):
            try:
                xml_text = request_xml(
                    "getRoadTrafficInfoList",
                    {"serviceKey": args.service_key, "routeId": rid},
                    timeout=args.request_timeout,
                    retries=args.retries,
                    backoff_sec=args.backoff_sec,
                )
            except Exception as exc:
                failures.append(
                    {
                        "routeId": rid,
                        "status": "request_error",
                        "headerCd": "",
                        "headerMsg": "",
                        "error": str(exc),
                    }
                )
                continue

            header = parse_header(xml_text)
            if header.get("headerCd") != "0":
                failures.append(
                    {
                        "routeId": rid,
                        "status": "api_header_error",
                        "headerCd": header.get("headerCd", ""),
                        "headerMsg": header.get("headerMsg", ""),
                        "error": "",
                    }
                )
                continue

            rows = extract_record_list(xml_text)
            for row in rows:
                row["routeId_query"] = rid
            recollected_rows.extend(rows)

            if args.sleep_per_route > 0:
                time.sleep(args.sleep_per_route)

            if idx % 25 == 0:
                print(f"[progress] routes={idx}/{len(route_ids)} rows={len(recollected_rows)} failures={len(failures)}")

        base_rows = []
        if base_traffic_csv.exists():
            with base_traffic_csv.open("r", newline="", encoding="utf-8") as f:
                base_rows = list(csv.DictReader(f))

        merged_rows = merge_dedup_rows(base_rows, recollected_rows)

        write_csv(out_csv, merged_rows)
        write_csv(failure_csv, failures)

        summary.update(
            {
                "route_csv": str(route_csv),
                "base_traffic_csv": str(base_traffic_csv),
                "out_csv": str(out_csv),
                "failure_csv": str(failure_csv),
                "route_count": len(route_ids),
                "recollected_row_count": len(recollected_rows),
                "base_row_count": len(base_rows),
                "merged_row_count": len(merged_rows),
                "failure_count": len(failures),
                "route_info_refreshed": refreshed,
            }
        )

        summary_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(summary, ensure_ascii=False, indent=2))

    except Exception as exc:
        summary["fatal_error"] = str(exc)
        summary_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        raise


if __name__ == "__main__":
    main()
