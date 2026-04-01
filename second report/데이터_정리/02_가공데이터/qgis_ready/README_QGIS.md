# QGIS 로딩 가이드

"
        "생성 기준: EPSG:4326 (WGS84)

"
        "## 권장 사용 순서
"
        "1. `qgis_ready/geojson` 폴더의 레이어를 QGIS에 드래그 앤 드롭
"
        "2. 후보지 분석은 `cctv_candidate_locations.geojson` 또는 시나리오 분리 레이어 사용
"
        "3. 속성 테이블에서 `유형`, `근거`, `cctv_coverage_m`, `bus_influence_m`로 필터링

"
        "## CSV 직접 로딩 시
"
        "- X field: `longitude`
"
        "- Y field: `latitude`
"
        "- Geometry CRS: `EPSG:4326`

"
        "세부 레이어 목록은 `layer_catalog.csv` 참고
"
        