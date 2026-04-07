# this 데이터 재분석(도로+교통량) 연속 그라데이션 가이드

## 1) 사용 파일

아래 파일을 기준으로 작업합니다.

- 경계
   - `this_uiwang_boundary.geojson`

- 점수 격자(둘 중 1개 선택)
   - `this_uiwang_roads_equal_grid_score_250m.gpkg`
   - `this_uiwang_roads_weighted_grid_score_250m.gpkg`

- 후보 포인트(라벨용, 선택)
   - `this_uiwang_roads_equal_candidate_points_top150_250m.geojson`
   - `this_uiwang_roads_weighted_candidate_points_top150_250m.geojson`

## 2) 목표

- 격자 폴리곤 경계선을 숨기고, 점수 분포를 연속 표면처럼 표현합니다.
- `equal` 또는 `weighted` 중 원하는 버전을 선택해서 같은 절차로 만들 수 있습니다.

## 3) QGIS 작업 순서 (중심점 생성 → IDW → 경계 클립)

### Step A. 점수 격자 로드

1. `this_uiwang_roads_weighted_grid_score_250m.gpkg`(또는 equal)를 추가합니다.
2. GPKG의 `grid_score` 레이어를 사용합니다.

### Step B. 격자를 중심점으로 변환

1. 메뉴: `Vector geometry` → `Centroids`
2. Input layer: `grid_score`
3. 출력 레이어 예시: `weighted_score_centroids`

### Step C. 점수 보간 래스터 생성 (IDW)

1. 메뉴: `Interpolation` → `IDW interpolation`
2. Input layer: `weighted_score_centroids` (또는 equal 중심점)
3. Interpolation attribute:
    - weighted 사용 시: `total_score_weighted_0_100`
    - equal 사용 시: `total_score_equal_0_100`
4. Distance coefficient(P): `2.0`
5. Pixel size: `20~40`m (권장 30m)
6. Extent: `this_uiwang_boundary` 기준
7. 출력 예시: `uiwang_weighted_idw.tif`

### Step D. 의왕시 경계로 클리핑

1. 메뉴: `Raster` → `Extraction` → `Clip raster by mask layer`
2. Input raster: IDW 결과 래스터
3. Mask layer: `this_uiwang_boundary`
4. `Crop to mask layer extent` 체크
5. 출력 예시: `uiwang_weighted_idw_clip.tif`

### Step E. 연속 그라데이션 스타일

1. 클립된 래스터 우클릭 → `속성` → `Symbology`
2. Render type: `Singleband pseudocolor`
3. Mode: `Continuous`
4. Interpolation: `Linear`
5. Color ramp: `Spectral (Reversed)` 또는 `YlOrRd`

## 4) 보고서용 레이어 추천

1. 하단: 배경지도
2. 중단: `uiwang_*_idw_clip.tif` (연속 위험도 표면)
3. 상단:
    - 기존 CCTV
    - 버스정류소, 학교, 사고다발, 사망사고
    - `this_uiwang_roads_weighted_candidate_points_top150_250m.geojson` 라벨 (`priority_rank <= 20`)

## 5) 재생성 명령

`second report/gpt` 폴더에서 실행:

- 기본
   - `python3 build_uiwang_grid_candidates_with_roads.py`

- 옵션 예시
   - `python3 build_uiwang_grid_candidates_with_roads.py --grid-size 200 --top-n 120`
   - `python3 build_uiwang_grid_candidates_with_roads.py --min-cctv-gap 250 --max-road-dist 120`
