# 의왕시 도로/교통량 조사 간단 분석

## 한줄 결론
- 의왕시 도로 세그먼트 2,665개는 경계 검증에서 외부(Outside) 0건으로 확인되었고,
- 교통량은 경기도 주요도로 API 특성상 직접 매칭은 305개(11.44%)에 그치지만, 추정 보강 적용 시 1,919개(72.01%)까지 실효 커버리지가 확장된다.

## 이번 추가 작업 (2026-04-07)
- OSM 원시데이터 필터링 스크립트 보강:
	- 파일: plus/build_uiwang_osm_road_inventory.py
	- 추가 기능: drivable 전용 필터(--drivable-only), 접미사 출력(--output-suffix)
	- 목적: 원시 OSM 고속/간선/생활도로만 분리해 재실행 가능한 필터링 파이프라인 확보
- OSM drivable 필터 재실행 완료:
	- 결과: raw_way 10,373 -> drivable segment 1,918, named road 340, 총연장 416.214km
	- 산출물: plus/uiwang_osm_roads_filtered_drivable.geojson, plus/uiwang_osm_stats_drivable.json
- 경기 API 재수집 스크립트 작성:
	- 파일: plus/build_gg_road_traffic_recollect.py
	- 추가 기능: route 단위 재시도/백오프, 실패 route CSV, 기존 traffic CSV와 중복 제거 병합
	- 목적: API 일시 장애/route별 실패가 있어도 전체 수집을 중단하지 않고 재수집 가능
- 교통량 추정 보강 실행:
	- 파일: plus/build_uiwang_road_traffic_infer.py
	- 결과: observed 305(11.44%) + inferred 1,614 => effective coverage 72.01% (전체 2,665 기준)
	- drivable 기준: observed 304(15.85%) + inferred 1,614 => effective coverage 100%
- inferred 반영 후보지 재산출:
	- 파일: second report/gpt/build_uiwang_grid_candidates_with_roads.py
	- 입력: plus/uiwang_all_roads_with_traffic_lines_in_boundary_inferred.geojson
	- 출력: this_uiwang_grid_score_30m_equal_inferred.gpkg, this_uiwang_grid_score_30m_weighted_inferred.gpkg
- 대체 소스 재시도 수행(road.re.kr):
	- 수집: road 433행, spot 3,331행, 의왕 연관 spot 277개
	- 결과: matched 305 -> 305 (11.44%), 추가 매칭 0건
	- 해석: 호출 성공 여부가 아니라 노선 체계/명칭 정합이 핵심 병목

## 조사/출처 정리
- 전체 조사 출처 및 상태는 CSV로 정리: plus/uiwang_investigation_sources.csv
- 통합 결과(도로+교통량): plus/uiwang_all_roads_with_traffic.csv
- 도로명 단위 요약: plus/uiwang_named_roads_with_traffic_summary.csv
- 추정 반영 통합 결과: plus/uiwang_all_roads_with_traffic_inferred.csv
- 추정 반영 커버리지: plus/uiwang_traffic_data_coverage_inferred.json
- road.re 재시도 결과: plus/uiwang_traffic_data_coverage_roadre_retry.json
- 경기 API 재수집 실행 결과(생성 대상):
	- plus/gg_road_traffic_info_list_recollected.csv
	- plus/gg_road_traffic_recollect_failures.csv
	- plus/gg_road_traffic_recollect_summary.json

## 도로 위치 검증 결과(꼼꼼 확인)
- 검증 파일: plus/uiwang_road_boundary_validation.csv
- 요약 파일: plus/uiwang_road_boundary_validation_summary.csv
- 품질 체크 파일: plus/uiwang_road_quality_checks.csv

요약 수치:
- inside: 2,479개 (490.968km)
- crossing_boundary: 186개 (129.060km)
- outside: 0개
- invalid_coordinates: 0개
- duplicate_way_id: 0개
- missing_highway: 0개

해석:
- crossing_boundary는 의왕 경계를 가로지르는 도로(경계 인접/통과)로, 의왕과 인접 시군을 함께 지나는 정상 케이스다.
- outside 0개이므로 최종 도로 세트는 의왕 경계와 무관한 도로가 포함되지 않았다.

## 교통량 매칭 분석
- 경기도 소통정보 원천 행: 24,413행
- 도로명 직접 매칭: 1,205행 사용
- 노선번호(ref/routeNo) 매칭: 4,794행 사용
- 이름 있는 도로 매칭: 17/362
- 세그먼트 직접 매칭(observed): 305/2,665 (11.44%)
- 세그먼트 추정 보강(inferred): 1,614개
- 세그먼트 실효 커버리지(observed+inferred): 1,919/2,665 (72.01%)
- drivable 실효 커버리지: 1,918/1,918 (100.0%)

해석:
- 경기도 API는 주요도로 중심이어서 생활도로/골목길은 교통량 정보가 비어 있는 것이 자연스럽다.
- 따라서 교통량 공란은 수집 실패라기보다 원천 데이터 범위 제한에 가깝다.

## 대체 사이트 점검 결과
- road.re.kr itms_22 계열: 접근 성공, 데이터 수집 성공, 추가 매칭 0건
- VWorld upisuq151: 본 환경에서 502
- 한국도로공사 trafficAll(data.ex.co.kr): DNS는 되지만 TCP 443 timeout

## 실행 예시
- OSM 드라이버블 도로만 필터링:
	- python plus/build_uiwang_osm_road_inventory.py --drivable-only
- 경기 API 교통량 재수집(기존 결과 병합):
	- python plus/build_gg_road_traffic_recollect.py --service-key <KEY> --refresh-route-list
- 교통량 추정 보강 실행:
	- python plus/build_uiwang_road_traffic_infer.py
- inferred 반영 후보지 재산출:
	- python "second report/gpt/build_uiwang_grid_candidates_with_roads.py" --roads-path plus/uiwang_all_roads_with_traffic_lines_in_boundary_inferred.geojson --output-tag inferred

## 신뢰도 판단
- 도로 위치 정확도: 높음 (경계 검증 outside 0)
- 교통량 대표성: 관측 기준 중간(주요도로 중심), 추정 보강 기준 중상(실효 72.01%, drivable 100%)
- 재현성: 높음 (수집/매칭 스크립트 포함)
