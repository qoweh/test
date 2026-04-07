#!/usr/bin/env python3
import argparse
import csv
import json
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path


BASE_URL = "https://openapigits.gg.go.kr/api/rest"


def request_xml(endpoint: str, params: dict, timeout: int = 30, retries: int = 1) -> str:
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
                time.sleep(0.5)

    raise last_error


def parse_header(xml_text: str) -> dict:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return {"headerCd": None, "headerMsg": "XML parse error"}

    cd = root.findtext(".//headerCd")
    msg = root.findtext(".//headerMsg")
    item_count = root.findtext(".//itemCount")
    return {"headerCd": cd, "headerMsg": msg, "itemCount": item_count}


def _element_to_dict(el: ET.Element) -> dict:
    out = {}
    for c in list(el):
        out[c.tag] = (c.text or "").strip()
    return out


def extract_record_list(xml_text: str):
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []

    # Common case: <msgBody><itemList>...</itemList></msgBody>
    item_lists = root.findall(".//itemList")
    records = []
    for node in item_lists:
        children = list(node)
        if children:
            # itemList contains child objects.
            for c in children:
                d = _element_to_dict(c)
                if d:
                    records.append(d)
        else:
            # itemList may itself be an item object.
            d = _element_to_dict(node)
            if d:
                records.append(d)

    if records:
        return records

    # Generic fallback: find repeated sibling groups.
    best_parent = None
    best_size = 0
    for parent in root.iter():
        children = list(parent)
        if len(children) < 2:
            continue
        tags = [c.tag for c in children]
        if len(set(tags)) == 1:
            count_nonempty = sum(1 for c in children if len(list(c)) > 0)
            if count_nonempty == len(children) and len(children) > best_size:
                best_parent = parent
                best_size = len(children)

    if best_parent is None:
        return []

    for c in list(best_parent):
        d = _element_to_dict(c)
        if d:
            records.append(d)

    return records


def write_csv(path: Path, rows: list):
    if not rows:
        path.write_text("", encoding="utf-8")
        return

    fieldnames = sorted({k for row in rows for k in row.keys()})
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description="Collect Gyeonggi road and traffic API data")
    parser.add_argument("--service-key", required=True, help="OpenAPIGITS service key")
    parser.add_argument("--max-routes", type=int, default=999999, help="Maximum route IDs to fetch")
    parser.add_argument("--out-dir", default="plus", help="Output directory")
    parser.add_argument(
        "--save-raw",
        action="store_true",
        help="Save raw XML responses under out-dir/raw_api",
    )
    parser.add_argument("--request-timeout", type=int, default=30, help="HTTP timeout seconds")
    parser.add_argument("--retries", type=int, default=1, help="Retries per request")
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    raw_dir = out_dir / "raw_api"
    if args.save_raw:
        raw_dir.mkdir(parents=True, exist_ok=True)

    summary = {
        "service": "openapigits.gg.go.kr",
        "steps": [],
        "requestTimeoutSec": args.request_timeout,
        "retries": args.retries,
    }

    # 1) Road list
    try:
        road_xml = request_xml(
            "getRoadInfoList",
            {"serviceKey": args.service_key},
            timeout=args.request_timeout,
            retries=args.retries,
        )
    except Exception as exc:
        summary["fatalError"] = f"getRoadInfoList request failed: {exc}"
        (out_dir / "gg_collection_summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return

    if args.save_raw:
        (raw_dir / "gg_getRoadInfoList.xml").write_text(road_xml, encoding="utf-8")
    road_header = parse_header(road_xml)
    road_records = extract_record_list(road_xml)
    write_csv(out_dir / "gg_road_info_list.csv", road_records)

    summary["steps"].append(
        {
            "endpoint": "getRoadInfoList",
            **road_header,
            "recordCount": len(road_records),
        }
    )

    # Stop if key or request failed.
    if road_header.get("headerCd") != "0":
        (out_dir / "gg_collection_summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return

    route_ids = []
    for r in road_records:
        rid = (r.get("routeId") or "").strip()
        if rid and rid not in route_ids:
            route_ids.append(rid)

    route_ids = route_ids[: args.max_routes]

    link_info_rows = []
    traffic_rows = []
    failures = []

    for rid in route_ids:
        link_header = {}
        traffic_header = {}
        request_errors = {}

        try:
            link_xml = request_xml(
                "getRoadLinkInfoList",
                {"serviceKey": args.service_key, "routeId": rid},
                timeout=args.request_timeout,
                retries=args.retries,
            )
            if args.save_raw:
                (raw_dir / f"gg_getRoadLinkInfoList_{rid}.xml").write_text(link_xml, encoding="utf-8")
            link_header = parse_header(link_xml)
            link_rows = extract_record_list(link_xml)
            for row in link_rows:
                row["routeId_query"] = rid
            link_info_rows.extend(link_rows)
        except Exception as exc:
            request_errors["getRoadLinkInfoList"] = str(exc)

        try:
            traffic_xml = request_xml(
                "getRoadTrafficInfoList",
                {"serviceKey": args.service_key, "routeId": rid},
                timeout=args.request_timeout,
                retries=args.retries,
            )
            if args.save_raw:
                (raw_dir / f"gg_getRoadTrafficInfoList_{rid}.xml").write_text(traffic_xml, encoding="utf-8")
            traffic_header = parse_header(traffic_xml)
            t_rows = extract_record_list(traffic_xml)
            for row in t_rows:
                row["routeId_query"] = rid
            traffic_rows.extend(t_rows)
        except Exception as exc:
            request_errors["getRoadTrafficInfoList"] = str(exc)

        if (
            request_errors
            or (link_header and link_header.get("headerCd") != "0")
            or (traffic_header and traffic_header.get("headerCd") != "0")
        ):
            failures.append(
                {
                    "routeId": rid,
                    "linkInfoHeader": link_header,
                    "trafficHeader": traffic_header,
                    "requestErrors": request_errors,
                }
            )

    write_csv(out_dir / "gg_road_link_info_list.csv", link_info_rows)
    write_csv(out_dir / "gg_road_traffic_info_list.csv", traffic_rows)

    summary["steps"].append(
        {
            "endpoint": "getRoadLinkInfoList",
            "routeQueryCount": len(route_ids),
            "recordCount": len(link_info_rows),
        }
    )
    summary["steps"].append(
        {
            "endpoint": "getRoadTrafficInfoList",
            "routeQueryCount": len(route_ids),
            "recordCount": len(traffic_rows),
        }
    )

    if failures:
        summary["failures"] = failures

    (out_dir / "gg_collection_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
