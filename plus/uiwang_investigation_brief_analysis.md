# 의왕시 도로/교통량 조사 간단 분석

## 한줄 결론
- 의왕시 도로 세그먼트 2,665개는 경계 검증에서 외부(Outside) 0건으로 확인되었고,
- 교통량은 경기도 주요도로 API 특성상 전체 도로 중 일부(세그먼트 기준 269개)에만 직접 매칭된다.

## 조사/출처 정리
- 전체 조사 출처 및 상태는 CSV로 정리: plus/uiwang_investigation_sources.csv
- 통합 결과(도로+교통량): plus/uiwang_all_roads_with_traffic.csv
- 도로명 단위 요약: plus/uiwang_named_roads_with_traffic_summary.csv

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
- 이름 있는 도로 매칭: 14/362
- 세그먼트 매칭: 269/2,665

해석:
- 경기도 API는 주요도로 중심이어서 생활도로/골목길은 교통량 정보가 비어 있는 것이 자연스럽다.
- 따라서 교통량 공란은 수집 실패라기보다 원천 데이터 범위 제한에 가깝다.

## 신뢰도 판단
- 도로 위치 정확도: 높음 (경계 검증 outside 0)
- 교통량 대표성: 중간 (주요도로 중심)
- 재현성: 높음 (수집/매칭 스크립트 포함)
