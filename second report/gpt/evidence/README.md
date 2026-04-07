# evidence 폴더 안내

## 구조

- original: 요소별 원본 파일
- csv: 보고서/검증용 CSV 증거 파일

## 원본 파일

- 무인교통단속카메라.gpkg
- 버스정류소.gpkg
- 초중고등학교.gpkg
- 사고다발지.gpkg
- 사망교통사고.gpkg
- uiwang_all_roads_with_traffic_lines_in_boundary.geojson

## CSV 파일

- 01_cctv_evidence.csv
  - 카메라 관리번호, 설치장소, 단속구분, 제한속도, 주소, 좌표
- 02_bus_stop_evidence.csv
  - 정류소명(한/영), 정류소 코드, 유형, 주소(raw), 좌표
- 03_school_evidence.csv
  - 학교ID, 학교명, 학교급, 설립형태, 운영상태, 주소, 좌표
- 04_accident_hotspot_evidence.csv
  - 사고다발지 원본 핵심 raw 필드(연도/유형/위치/건수), 좌표
- 05_fatal_accident_evidence.csv
  - 사망교통사고 원본 핵심 raw 필드(연도/일자/시간대/기상/건수), 좌표
- 06_road_traffic_evidence.csv
  - 도로 기본속성 + 매칭 교통량(평균/최소/최대), 경계검증 상태, 중심좌표

## 참고

- CSV는 원본 행 수와 1:1로 맞춰 생성했습니다.
- 사고다발지/사망교통사고는 원본 필드 인코딩 이슈가 있어 raw 필드명을 유지해 정리했습니다.
