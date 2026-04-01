# this 데이터 재분석 결과 + QGIS 시각화 방법

## 1) 이번에 다시 만든 핵심 결과

원본 데이터는 `this` 폴더 GPKG 5개만 사용했습니다.

- `this_uiwang_grid_score_250m.gpkg`
  - 전체 격자(폴리곤) 937개 + 점수
  - QGIS에서 가장 권장
- `this_uiwang_grid_score_250m.geojson`
  - 동일 내용의 GeoJSON 버전(폴리곤)
- `this_uiwang_candidate_cells_top150_250m.geojson`
  - 후보 격자(폴리곤)만 필터
- `this_uiwang_candidate_points_top150_250m.geojson`
  - 후보 중심점(라벨용)
- `this_uiwang_boundary.geojson`
  - 의왕시 경계
- `this_uiwang_inputs_points.geojson`
  - 입력 포인트 QA용(카메라/버스/사고/학교)
- `this_uiwang_grid_summary.json`
  - 입력/출력 건수 요약

## 2) 점수 계산 요약

- 격자 크기: 250m
- 점수 원리:
  - 기존 카메라와 멀수록 점수 상승
  - 버스정류소/사고다발지/사망사고/학교와 가까울수록 점수 상승
- 최종 점수:
  - `total_score_0_100` (0~100)
- 후보 플래그:
  - `candidate_flag = true`

## 3) QGIS에서 "격자 전체 색칠"로 보는 방법

1. 레이어 추가
- `this_uiwang_boundary.geojson`
- `this_uiwang_grid_score_250m.gpkg` (레이어명: `grid_score`)
- 필요시 `this_uiwang_candidate_points_top150_250m.geojson`

2. 격자 레이어 심볼 설정
- 대상: `grid_score`
- Symbology: `Graduated`
- Column: `total_score_0_100`
- Mode: `Quantile (Equal Count)`
- Classes: `7`
- Color ramp: `Reds` (또는 `YlOrRd`)

3. 지도처럼 격자 칠하기
- Fill opacity: `70~85%`
- Stroke color: 진회색
- Stroke width: `0.1~0.2`
- 이 상태가 요청하신 "지도 전체 격자 색칠" 형태입니다.

4. 후보지만 강조(옵션)
- `candidate_flag = true` 필터 레이어 복제
- 윤곽선 두껍게(예: 0.6), 색은 검정/진빨강
- 필요시 중심점 레이어 라벨: `priority_rank`

## 4) 자주 생기는 실수

- 점만 보이는 경우:
  - `this_uiwang_candidate_points_top150_250m.geojson`만 올린 상태입니다.
  - 반드시 `this_uiwang_grid_score_250m.gpkg`를 같이 올려야 격자 색칠이 보입니다.

- 격자가 안 칠해지는 경우:
  - 심볼이 `Single Symbol`로 되어 있음 -> `Graduated`로 변경 필요

## 5) 재실행 명령

`/bin/python3 build_uiwang_grid_candidates.py`

옵션 예시:

- 200m 격자:
  - `/bin/python3 build_uiwang_grid_candidates.py --grid-size 200`
- 후보 거리 기준 250m:
  - `/bin/python3 build_uiwang_grid_candidates.py --min-cctv-gap 250`
