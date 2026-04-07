# this 데이터 30m 래스터(IDW) 전용 가이드

## 1) 남겨둔 파일

- `this_uiwang_boundary.geojson`
- `this_uiwang_grid_score_30m_equal.gpkg`
- `this_uiwang_grid_score_30m_weighted.gpkg`
- `build_uiwang_grid_candidates_with_roads.py`

## 2) equal / weighted 차이

- equal: 요소 동일 가중치
- weighted: 지정 가중치(사망 5, CCTV 거리 2, 학교 3, 버스 3, 사고다발 5, 교통량 5)

두 파일 모두 같은 구조입니다.

- 레이어 `grid_score`: 30m 격자 폴리곤 점수
- 레이어 `score_points`: IDW 바로 입력 가능한 점 레이어
- IDW 필드: `total_score_0_100`

## 3) QGIS에서 래스터(IDW) 만드는 순서

1. `this_uiwang_grid_score_30m_weighted.gpkg`(또는 equal) 추가
2. 레이어는 `score_points` 선택
3. `Interpolation` -> `IDW interpolation`
   - Input layer: `score_points`
   - Attribute: `total_score_0_100`
   - Distance coefficient(P): `2.0`
   - Pixel size: 20~40m (권장 30m)
4. `Clip raster by mask layer`
   - Mask: `this_uiwang_boundary.geojson`
5. 결과 래스터를 `Singleband pseudocolor` + `Continuous`로 스타일링

## 4) 재생성 명령

`second report/gpt` 폴더에서 실행:

- `python3 build_uiwang_grid_candidates_with_roads.py --grid-size 30`

스크립트 실행 후 아래 두 파일이 다시 생성됩니다.

- `this_uiwang_grid_score_30m_equal.gpkg`
- `this_uiwang_grid_score_30m_weighted.gpkg`
