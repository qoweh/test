# 의왕시 후보지(도로 위치-구간 + 교통량 포함) QGIS 가이드

## 1) 현재 결과 파일

- 경계
  - `this_uiwang_boundary.geojson`

- 동일 가중치 버전 (equal)
  - `this_uiwang_roads_equal_grid_score_250m.geojson`
  - `this_uiwang_roads_equal_grid_score_250m.gpkg`
  - `this_uiwang_roads_equal_grid_score_250m.csv`
  - `this_uiwang_roads_equal_candidate_cells_top150_250m.geojson`
  - `this_uiwang_roads_equal_candidate_points_top150_250m.geojson`
  - `this_uiwang_roads_equal_candidate_top150_250m.csv`

- 지정 가중치 버전 (weighted)
  - `this_uiwang_roads_weighted_grid_score_250m.geojson`
  - `this_uiwang_roads_weighted_grid_score_250m.gpkg`
  - `this_uiwang_roads_weighted_grid_score_250m.csv`
  - `this_uiwang_roads_weighted_candidate_cells_top150_250m.geojson`
  - `this_uiwang_roads_weighted_candidate_points_top150_250m.geojson`
  - `this_uiwang_roads_weighted_candidate_top150_250m.csv`

- 요약/보조
  - `this_uiwang_grid_summary_with_roads.json`
  - `this_uiwang_inputs_points_with_roads.geojson`

## 2) 주요 필드 의미

- 거리 필드
  - `dist_cctv_m`: 기존 CCTV까지 거리 (멀수록 유리)
  - `dist_school_m`, `dist_bus_m`, `dist_accident_m`, `dist_fatal_m`: 각 취약지점까지 거리 (가까울수록 유리)
  - `dist_road_m`: 최근접 도로 선형까지 거리 (가까울수록 유리)

- 도로/교통 필드
  - `nearest_road_way_id`, `nearest_road_name`, `nearest_road_highway`
  - `nearest_road_vol_mean`: 최근접 도로의 평균 교통량 값

- 정규화 점수 (0~1)
  - `score_cctv_gap_0_1`, `score_school_0_1`, `score_bus_0_1`, `score_accident_0_1`, `score_fatal_0_1`
  - `score_road_proximity_0_1`, `score_traffic_0_1`

- 최종 점수 (0~100)
  - `total_score_equal_0_100`: 7요소 동일 가중 평균
  - `total_score_weighted_0_100`: 지정 가중치 버전

- 후보 조건
  - `candidate_flag = true`는 아래 필터를 통과한 상위 후보
    - `dist_cctv_m >= min_cctv_gap_m` (기본 200m)
    - `dist_road_m <= max_road_dist_m` (기본 150m)

## 3) 두 버전 차이

- `equal`
  - CCTV 간격, 학교, 버스, 사고다발, 사망사고, 도로 근접, 교통량을 동일 비중으로 반영

- `weighted`
  - 사용자 지정 가중치 반영
  - 사망사고 5, CCTV 거리 2, 학교 3, 버스 3, 사고다발 5, 교통량 5
  - 도로 위치-구간은 후보 필터(`dist_road_m <= max_road_dist_m`)로 강제 반영

## 4) QGIS에서 표시하는 방법

1. 아래 레이어를 추가합니다.
   - `this_uiwang_boundary.geojson`
   - `this_uiwang_roads_weighted_grid_score_250m.geojson` (또는 equal 파일)
   - `this_uiwang_roads_weighted_candidate_points_top150_250m.geojson` (또는 equal 파일)

2. 격자 레이어 스타일을 `Graduated`로 설정합니다.
   - weighted 지도: `total_score_weighted_0_100`
   - equal 지도: `total_score_equal_0_100`
   - Color ramp: `YlOrRd` 또는 `Spectral`
   - Classes: 7

3. 후보 강조를 위해 Rule-based 표시를 적용합니다.
   - Rule 1: `"candidate_flag" = true` (투명 채우기 + 진한 외곽선)
   - Rule 2: `"candidate_flag" = false` (연한 색 + 얇은 외곽선)

4. 후보 포인트 라벨
   - Label field: `priority_rank`
   - 상위 20개만: `"priority_rank" <= 20`

## 5) 재생성 명령

같은 폴더(`second report/gpt`)에서 실행합니다.

- 기본 실행
  - `python3 build_uiwang_grid_candidates_with_roads.py`

- 파라미터 변경 예시
  - `python3 build_uiwang_grid_candidates_with_roads.py --grid-size 200 --top-n 120`
  - `python3 build_uiwang_grid_candidates_with_roads.py --min-cctv-gap 250 --max-road-dist 120`

## 6) 해석 시 주의사항

- 점수는 우선순위 선정을 위한 정량 지표입니다.
- 최종 설치는 현장 시야, 도로 구조, 전원/통신 인입, 민원 및 법적 기준을 함께 검토해야 합니다.
