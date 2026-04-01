import json
from pathlib import Path

import numpy as np
import pandas as pd

BASE = Path(__file__).resolve().parent
DATA = BASE / "자료"
OUT = BASE / "qgis_ready"
OUT_CSV = OUT / "csv"
OUT_GEOJSON = OUT / "geojson"


def ensure_dirs():
    OUT.mkdir(exist_ok=True)
    OUT_CSV.mkdir(exist_ok=True)
    OUT_GEOJSON.mkdir(exist_ok=True)


def add_geom_columns(df, lat_col="위도", lon_col="경도"):
    out = df.copy()
    out[lat_col] = pd.to_numeric(out[lat_col], errors="coerce")
    out[lon_col] = pd.to_numeric(out[lon_col], errors="coerce")
    out = out.dropna(subset=[lat_col, lon_col]).copy()
    out["latitude"] = out[lat_col]
    out["longitude"] = out[lon_col]
    out["x"] = out[lon_col]
    out["y"] = out[lat_col]
    out["epsg"] = "EPSG:4326"
    out["wkt"] = out.apply(lambda r: f"POINT ({r[lon_col]} {r[lat_col]})", axis=1)
    return out


def to_geojson(df, lat_col="latitude", lon_col="longitude"):
    features = []
    for _, row in df.iterrows():
        props = {}
        for c in df.columns:
            if c in [lat_col, lon_col, "x", "y", "wkt"]:
                continue
            v = row[c]
            if isinstance(v, (np.integer, np.floating)):
                if np.isnan(v):
                    v = None
                else:
                    v = float(v) if isinstance(v, np.floating) else int(v)
            props[c] = v
        features.append(
            {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [float(row[lon_col]), float(row[lat_col])],
                },
                "properties": props,
            }
        )
    return {"type": "FeatureCollection", "name": "layer", "features": features}


def save_layer(df, layer_name, lat_col="위도", lon_col="경도", extra_desc=""):
    gdf = add_geom_columns(df, lat_col=lat_col, lon_col=lon_col)
    csv_path = OUT_CSV / f"{layer_name}.csv"
    geojson_path = OUT_GEOJSON / f"{layer_name}.geojson"

    gdf.to_csv(csv_path, index=False, encoding="utf-8-sig")
    geo = to_geojson(gdf)
    geo["crs"] = {"type": "name", "properties": {"name": "EPSG:4326"}}
    with geojson_path.open("w", encoding="utf-8") as f:
        json.dump(geo, f, ensure_ascii=False, indent=2)

    return {
        "layer_name": layer_name,
        "rows": len(gdf),
        "csv_file": str(csv_path.relative_to(BASE)).replace("\\", "/"),
        "geojson_file": str(geojson_path.relative_to(BASE)).replace("\\", "/"),
        "lat_col": "latitude",
        "lon_col": "longitude",
        "epsg": "EPSG:4326",
        "description": extra_desc,
    }


def main():
    ensure_dirs()
    catalog = []

    traffic = pd.read_csv(BASE / "traffic_cctv_uiwang.csv", encoding="utf-8-sig")
    catalog.append(
        save_layer(
            traffic,
            "traffic_cctv_uiwang",
            lat_col="위도",
            lon_col="경도",
            extra_desc="의왕시 교통단속 CCTV 위치(최종 분석용)",
        )
    )

    hotspots = pd.read_csv(BASE / "accident_hotspots.csv", encoding="utf-8-sig")
    catalog.append(
        save_layer(
            hotspots,
            "accident_hotspots",
            lat_col="위도",
            lon_col="경도",
            extra_desc="사고다발 및 사망사고 밀집 기반 핫스팟",
        )
    )

    bus = pd.read_csv(BASE / "bus_stop_uiwang.csv", encoding="utf-8-sig")
    catalog.append(
        save_layer(
            bus,
            "bus_stop_uiwang",
            lat_col="위도",
            lon_col="경도",
            extra_desc="의왕시 버스정류소 위치",
        )
    )

    cand = pd.read_csv(BASE / "cctv_candidate_locations.csv", encoding="utf-8-sig")
    catalog.append(
        save_layer(
            cand,
            "cctv_candidate_locations",
            lat_col="위도",
            lon_col="경도",
            extra_desc="시나리오 통합 CCTV 추가 설치 후보지",
        )
    )

    # 시나리오 분리 레이어
    acc_cand = cand[cand["유형"].isin(["사고다발", "복합"])].copy()
    for cov in sorted(acc_cand["cctv_coverage_m"].dropna().unique()):
        sub = acc_cand[acc_cand["cctv_coverage_m"] == cov].copy()
        if len(sub) == 0:
            continue
        catalog.append(
            save_layer(
                sub,
                f"candidates_accident_cov_{int(cov)}m",
                lat_col="위도",
                lon_col="경도",
                extra_desc=f"사고다발/복합 후보 (CCTV 커버리지 {int(cov)}m)",
            )
        )

    bus_cand = cand[cand["유형"].isin(["정류소", "복합"])].copy()
    for br in sorted(bus_cand["bus_influence_m"].dropna().unique()):
        sub = bus_cand[bus_cand["bus_influence_m"] == br].copy()
        if len(sub) == 0:
            continue
        catalog.append(
            save_layer(
                sub,
                f"candidates_bus_{int(br)}m",
                lat_col="위도",
                lon_col="경도",
                extra_desc=f"정류소/복합 후보 (정류소 영향 반경 {int(br)}m)",
            )
        )

    # 원천 위치 데이터도 QGIS용으로 정리
    fatal = pd.read_csv(DATA / "사망교통사고현황.csv", encoding="cp949")
    fatal = fatal[fatal["시군명"] == "의왕시"].copy()
    fatal = fatal.rename(columns={"WGS84위도": "위도", "WGS84경도": "경도"})
    catalog.append(
        save_layer(
            fatal,
            "fatal_accidents_uiwang",
            lat_col="위도",
            lon_col="경도",
            extra_desc="의왕시 사망교통사고 원천 위치",
        )
    )

    hot_raw = pd.read_csv(DATA / "사고다발지현황.csv", encoding="cp949")
    hot_raw = hot_raw[hot_raw["시군명"] == "의왕시"].copy()
    catalog.append(
        save_layer(
            hot_raw,
            "accident_hotspots_raw_uiwang",
            lat_col="위도",
            lon_col="경도",
            extra_desc="의왕시 사고다발지 원천 위치",
        )
    )

    catalog_df = pd.DataFrame(catalog)
    catalog_df.to_csv(OUT / "layer_catalog.csv", index=False, encoding="utf-8-sig")

    readme = OUT / "README_QGIS.md"
    readme.write_text(
        """# QGIS 로딩 가이드\n\n"
        "생성 기준: EPSG:4326 (WGS84)\n\n"
        "## 권장 사용 순서\n"
        "1. `qgis_ready/geojson` 폴더의 레이어를 QGIS에 드래그 앤 드롭\n"
        "2. 후보지 분석은 `cctv_candidate_locations.geojson` 또는 시나리오 분리 레이어 사용\n"
        "3. 속성 테이블에서 `유형`, `근거`, `cctv_coverage_m`, `bus_influence_m`로 필터링\n\n"
        "## CSV 직접 로딩 시\n"
        "- X field: `longitude`\n"
        "- Y field: `latitude`\n"
        "- Geometry CRS: `EPSG:4326`\n\n"
        "세부 레이어 목록은 `layer_catalog.csv` 참고\n"
        """,
        encoding="utf-8",
    )

    print("완료: qgis_ready 폴더 생성")
    print(f"레이어 수: {len(catalog_df)}")


if __name__ == "__main__":
    main()
