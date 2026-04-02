# this 데이터 재분석 결과 + QGIS 연속 그라데이션(격자 제거) 가이드

## 1) 사용 파일

아래 파일만 있으면 됩니다(격자 없이 바로 사용 가능).

- `this_uiwang_score_points_250m.gpkg` (레이어: `score_points`)
- `this_uiwang_score_points_250m.geojson`
- `this_uiwang_boundary.geojson`
- `this_uiwang_candidate_points_top150_250m.geojson` (상위 후보 라벨용, 선택)

핵심 점수 필드:

- `total_score_0_100` (높을수록 우선 설치 후보)

## 2) 목표

- 격자 블록(폴리곤) 표현 대신, 점수의 **연속 표면(그라데이션)** 지도를 만듭니다.
- 참고 이미지처럼 부드러운 색 변화가 나오도록 보간 래스터를 사용합니다.

## 3) QGIS 클릭 순서 (보간 → 클리핑 → 스타일)

### Step A. 점수 포인트 레이어 추가

1. `score_points` 레이어를 추가합니다.
2. 별도 중심점 생성은 필요 없습니다(이미 점 레이어).

### Step B. 점수 보간 래스터 생성 (IDW)

1. 메뉴: `처리도구상자` → `보간(Interpolation)` → `IDW interpolation`.
2. Input layer: `score_points`
3. Interpolation attribute: `total_score_0_100`
4. Distance coefficient(P): `2.0` (기본값 권장)
5. Pixel size: `20 ~ 40`m 권장 (예: 30m)
6. Extent: `this_uiwang_boundary` 범위로 설정
7. 출력: `uiwang_score_idw.tif`

### Step C. 의왕시 경계로 클리핑

1. 메뉴: `Raster` → `Extraction` → `Clip raster by mask layer`
2. Input raster: `uiwang_score_idw.tif`
3. Mask layer: `this_uiwang_boundary`
4. `Crop to mask layer extent` 체크
5. 출력: `uiwang_score_idw_clip.tif`

### Step D. 그라데이션 스타일 적용

1. `uiwang_score_idw_clip.tif` 우클릭 → `속성` → `Symbology`
2. Render type: `Singleband pseudocolor`
3. Color ramp: `Spectral (Reversed)` 또는 `RdYlBu (Reversed)`
4. Interpolation: `Linear`
5. Mode: `Continuous`
6. Class 개수는 10~20으로 두되, 표현은 연속형으로 유지

### Step E. 격자 레이어 미사용

- `grid_score` 폴리곤은 아예 로드하지 않아도 됩니다.
- 필요하면 후보 포인트/기존 CCTV만 상단에 겹쳐 표시합니다.

## 4) 참고 이미지처럼 더 부드럽게 보이게 하는 옵션

- `Raster` → `Analysis` → `Smoothing`(Gaussian/Mean) 약하게 1회
- 배경지도가 밝으면 래스터 투명도 `10~25%` 조정
- (선택) DEM 힐셰이드 위에 `Multiply/Overlay` 블렌딩으로 지형감 추가

## 5) 보고서용 권장 레이어 구성

1. 바닥: 배경지도(또는 힐셰이드)
2. 중간: `uiwang_score_idw_clip.tif` (연속 그라데이션)
3. 상단:
   - 기존 카메라(`무인교통단속카메라`)
   - 버스정류소/학교/사고다발지/사망사고
   - `this_uiwang_candidate_points_top150_250m.geojson` 라벨(`priority_rank <= 20`)

## 6) 재생성 명령 (점수 데이터 재산출이 필요할 때만)

`/bin/python3 /home/runner/work/qgis-second-report/qgis-second-report/second report/gpt/build_uiwang_grid_candidates.py`
