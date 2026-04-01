# 의왕시 무인교통단속카메라 후보지(그리드 점수) 사용 가이드

## 1) 생성된 결과 파일

- `uiwang_boundary.geojson`
  - 의왕시 경계(행정경계)
- `uiwang_grid_score_250m.geojson`
  - 250m 격자 폴리곤 + 점수 속성
- `uiwang_grid_score_250m.csv`
  - 같은 내용을 표 형태로 저장
- `uiwang_candidate_top120_250m.geojson`
  - 후보 격자 중심점(상위 후보)
- `uiwang_candidate_top120_250m.csv`
  - 후보 중심점 속성표
- `uiwang_grid_summary.json`
  - 입력/출력 건수 및 설정값 요약

## 2) 점수 의미

- `dist_cctv_m`: 가장 가까운 교통단속카메라까지 거리 (멀수록 좋음)
- `dist_bus_m`: 가장 가까운 버스정류소까지 거리 (가까울수록 좋음)
- `dist_accident_m`: 가장 가까운 사고다발지까지 거리 (가까울수록 좋음)
- `dist_fatal_m`: 가장 가까운 사망교통사고 지점까지 거리 (가까울수록 좋음)
- `dist_school_m`: 가장 가까운 학교까지 거리 (가까울수록 좋음)
- `vulnerability_0_1`: 취약지 근접 종합 점수
- `total_score_0_100`: 최종 후보 점수 (높을수록 우선 검토)
- `candidate_flag`: 후보 조건 통과 여부

## 3) QGIS에서 표시하는 방법

1. QGIS에서 아래 레이어를 추가합니다.
   - `uiwang_boundary.geojson`
   - `uiwang_grid_score_250m.geojson`
   - `uiwang_candidate_top120_250m.geojson`
2. `uiwang_grid_score_250m.geojson` 심볼을 `Graduated`로 변경합니다.
   - Column: `total_score_0_100`
   - Color ramp: `YlOrRd` 또는 `Spectral`
   - Classes: 7
3. 후보지 강조를 위해 Rule-based 레이어를 만듭니다.
   - Rule 1: `"candidate_flag" = true`
     - 채우기: 투명도 15~30%
     - 외곽선: 진한 빨강
   - Rule 2: `"candidate_flag" = false`
     - 채우기: 매우 연한 회색, 외곽선 얇게
4. `uiwang_candidate_top120_250m.geojson`에 라벨을 켭니다.
   - Label with: `priority_rank`
   - 상위 후보 20개만 보려면 Filter:
     - `"priority_rank" <= 20`

## 4) 보고서용 맵 3장 권장 구성

- 지도 A: 전체 점수 분포 (그리드 choropleth)
- 지도 B: 상위 후보 20개 + 기존 카메라 중첩
- 지도 C: 후보 + 취약지(버스/학교/사고다발/사망사고) 중첩

## 5) 점수 재생성(옵션)

같은 폴더에서 아래 명령으로 재실행할 수 있습니다.

- 기본(250m):
  - `/bin/python3 build_uiwang_grid_candidates.py`
- 더 세밀한 격자(200m):
  - `/bin/python3 build_uiwang_grid_candidates.py --grid-size 200`
- 카메라 최소 이격거리 변경(예: 250m):
  - `/bin/python3 build_uiwang_grid_candidates.py --min-cctv-gap 250`

## 6) 분석 주의사항

- 경계는 OSM 행정경계를 자동 조회해 사용했습니다.
- 좌표 오입력처럼 보이는 원천 이상점은 경계 기반 필터에서 자동 제외됩니다.
- 점수는 정책 우선순위 참고용이며, 최종 설치는 현장 여건(도로폭, 시야, 전원/통신 인입, 민원)을 추가 검토해야 합니다.
