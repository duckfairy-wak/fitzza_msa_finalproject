# 크롤링 데이터 DB 적재 가이드

백엔드 팀용 S3 크롤링 결과 적재 안내서입니다.

## 1. S3 접속 정보

- AWS 리전: `ap-northeast-2`
- 버킷: `s3://fitzza-prod-foundation-databucket-wwng6wfc0hqy`
- 실행 ID: `collection-20261025-01`
- 전체 실행 경로:

```text
s3://fitzza-prod-foundation-databucket-wwng6wfc0hqy/pipeline/runs/collection-20261025-01/
```

## 2. 적재 대상

### 상품 데이터

```text
pipeline/runs/collection-20261025-01/curated/data/<카테고리>/<상품ID>.json
```

카테고리 디렉터리를 순회하여 상품 JSON을 읽습니다.

검증 파일:

```text
pipeline/runs/collection-20261025-01/curated/manifest.json
pipeline/runs/collection-20261025-01/curated/report.json
```

`manifest.json`에 기록된 파일 목록과 SHA-256을 확인하여 누락이나 변조 여부를 검증합니다.

### 상품 이미지

```text
pipeline/runs/collection-20261025-01/images/products/<상품ID>/*
```

상품 JSON의 이미지 메타데이터와 S3 object key를 기존 상품 이미지 구조에 매핑합니다.

이번 실행 결과:

- 상품 수: 3,000개
- 다운로드 이미지: 28,569개
- 원본 404 등 실패: 64건

실패 목록은 다음 경로에 별도로 기록되어 있습니다.

```text
pipeline/runs/collection-20261025-01/audit/image-download-failures/products/<상품ID>.json
```

이 64건은 크롤러 전체 실패가 아니므로 DB 적재를 중단하지 말고, 해당 이미지 레코드만 누락 또는 실패 상태로 처리합니다.

### 리뷰 데이터

```text
pipeline/runs/collection-20261025-01/reviews/data/<상품ID>.json
```

이번 실행 결과:

- 리뷰 수: 87,434개
- 리뷰 이미지: 수집하지 않음

상품 ID를 외래키로 사용하여 기존 리뷰 테이블에 연결합니다. 리뷰 이미지 적재는 수행하지 않습니다.

### 실행 상태

```text
pipeline/runs/collection-20261025-01/status.json
```

최종 적재 전 `state: "succeeded"`, `product_count: 3000`인지 확인합니다.

## 3. 스키마 및 매핑 주의사항

- S3 데이터를 상품 서비스 DB에 직접 임의 매핑하지 말고, 기존 상품·이미지·리뷰 스키마에 맞춘 별도 import 배치로 적재합니다.
- 동일 상품 ID를 재처리해도 중복 insert가 발생하지 않도록 upsert 또는 실행 ID 기반 중복 방지를 적용합니다.
- 이미지 URL 자체보다 S3 object key를 저장하고, 서비스의 이미지 제공 방식에 맞춰 URL을 생성합니다.
- 외부 JSON 계약은 기존 스키마로 복원되어 있습니다. 내부 크롤러용 `size.source`, `size.options`, `color_status`를 DB 컬럼으로 추가할 필요는 없습니다.
- 색상이 명확하지 않은 상품은 기존 계약에 맞춰 `color_raw: "미지정"`으로 저장될 수 있습니다.
- 리뷰 이미지는 수집하지 않았으므로 빈 배열 또는 미수집 상태로 처리합니다.
- S3 버전 관리가 활성화되어 있으므로 기존 데이터 삭제보다 staging 적재 후 검증·운영 반영을 권장합니다.

## 4. 권장 적재 절차

```text
manifest/hash 검증
→ staging 테이블 적재
→ 상품·이미지·리뷰 외래키 검증
→ 상품 수·누락·중복 검증
→ 운영 테이블 반영
```

최소 검증 항목:

- 상품 JSON 총 3,000개
- `manifest.json` 파일 목록 및 SHA-256 일치
- 상품 ID 중복 없음
- 이미지 object key의 상품 ID 매칭
- 리뷰의 상품 ID 외래키 유효성
- 리뷰 총 87,434개와 적재 결과 비교
- 이미지 실패 64건이 예외 목록과 일치

## 5. 데이터 확인 명령어 예시

AWS CLI 프로필을 사용하는 경우:

```powershell
aws s3 cp s3://fitzza-prod-foundation-databucket-wwng6wfc0hqy/pipeline/runs/collection-20261025-01/status.json - --profile fitzza
aws s3 cp s3://fitzza-prod-foundation-databucket-wwng6wfc0hqy/pipeline/runs/collection-20261025-01/curated/manifest.json - --profile fitzza
```

운영 DB 반영 전에는 반드시 staging 적재 결과와 원본 S3 파일 수를 비교합니다.
