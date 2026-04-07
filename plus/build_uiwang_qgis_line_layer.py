#!/usr/bin/env python3
import csv
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent
IN_LINES = ROOT / "uiwang_osm_roads_filtered.geojson"
IN_ATTRS = ROOT / "uiwang_all_roads_with_traffic.csv"
OUT_LINES = ROOT / "uiwang_all_roads_with_traffic_lines.geojson"


def main():
    with IN_ATTRS.open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))

    attrs_by_way_id = {}
    for r in rows:
        way_id = str(r.get("way_id", "")).strip()
        if way_id:
            attrs_by_way_id[way_id] = r

    data = json.loads(IN_LINES.read_text(encoding="utf-8"))
    out_features = []

    for feature in data.get("features", []):
        props = feature.get("properties", {})
        way_id = str(props.get("way_id", "")).strip()

        merged_props = dict(props)
        if way_id in attrs_by_way_id:
            # Overwrite/add with the latest integrated traffic attributes.
            merged_props.update(attrs_by_way_id[way_id])

        out_features.append(
            {
                "type": "Feature",
                "geometry": feature.get("geometry"),
                "properties": merged_props,
            }
        )

    out_geojson = {
        "type": "FeatureCollection",
        "name": "uiwang_all_roads_with_traffic_lines",
        "features": out_features,
    }

    OUT_LINES.write_text(json.dumps(out_geojson, ensure_ascii=False), encoding="utf-8")

    matched = sum(
        1
        for ft in out_features
        if str(ft.get("properties", {}).get("traffic_match", "")) == "matched"
    )

    print(
        json.dumps(
            {
                "output": str(OUT_LINES),
                "feature_count": len(out_features),
                "traffic_matched_features": matched,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
