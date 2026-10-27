# Local / QA SQL seeds

| 파일 | 스키마 | 설명 |
|------|--------|------|
| `user_service_seed.sql` | `user_service` | 테스트 사용자 1001~1020 |
| `product_service_seed.sql` | `product_service` | 무신사 `4695999` 상품 1건 (`product_id` = 무신사 번호) |
| `product_service_wishlist_seed.sql` | `product_service` | user `1001` + product `4695999` 찜 1건 |
| `order_service_seed.sql` | `order_service` | user `1001`~`1005` 주문 6건(완료 5, 취소 1)·주문 항목 7개 — 리뷰·사이즈 설문 테스트용 |

## Apply order

```bash
set -a && source .env && set +a
docker compose exec -T postgres psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" < infra/seed/user_service_seed.sql
docker compose exec -T postgres psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" < infra/seed/product_service_seed.sql
docker compose exec -T postgres psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" < infra/seed/product_service_wishlist_seed.sql
docker compose exec -T postgres psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" < infra/seed/order_service_seed.sql
```

- 상품: `GET /api/v1/products/4695999`
- 찜: `seed01@fitzza.test` / `Fitzza1234` signin 후 `GET /api/v1/wishlists`
- 주문·리뷰·설문: `seed01@fitzza.test`로 signin 후 주문 항목 `1001`, `1002`로 `POST /api/v1/reviews`·`POST /api/v1/surveys`
- 취소 주문 거부: `seed05@fitzza.test`로 signin 후 주문 항목 `1007`로 요청하면 `ORDER_NOT_COMPLETED`(다른 계정으로 요청하면 소유권 오류 `NOT_ORDER_OWNER`가 먼저 난다)
- `-v ON_ERROR_STOP=1`: SQL 오류가 나면 거기서 멈추고 실패로 끝나게 한다(없으면 오류가 나도 명령이 성공한 것처럼 끝날 수 있다)

`product_service_seed.sql`은 `product_id`=무신사 번호, `option_id`=DB IDENTITY(`source_option_id`에 무신사 옵션 번호) 기준이다. Java musinsa JSON 시드와 별개 픽스처.

재실행 시 이미지·실측·wishlist·worldcup은 `product_id=4695999` 범위로 갱신하고,
기존 `source_option_id`의 `option_id`는 보존한다(장바구니·주문에 묶인 옵션 ID 유지).
wishlist·worldcup_history는 해당 상품 기준 사용자 구분 없이 삭제되므로 QA에서는 이 상품 관련 기록이 초기화된다.

## 크롤링 상품 (collection-20261025-01)

S3 curated 상품 JSON을 `product_service`에 upsert한다. 리뷰 적재와 분리되어 있으며, 리뷰는 별도 담당/스크립트를 쓴다.
운영 계약·검증 항목은 [DB_IMPORT_GUIDE.md](../data-pipeline/DB_IMPORT_GUIDE.md)를 본다.

```powershell
# 1) S3 다운로드 (AWS profile fitzza 필요). 이미지는 용량이 크므로 필요할 때만 --include-images
python -X utf8 scripts/download_curated_products.py --run-id collection-20261025-01

# 2) staging SQL 렌더 (Git/S3에 SQL 올리지 말 것)
python -X utf8 scripts/render_crawled_product_import.py `
  --data .data/collection-20261025-01/curated/data `
  --status .data/collection-20261025-01/status.json `
  --manifest .data/collection-20261025-01/curated/manifest.json `
  --images .data/collection-20261025-01/images/products `
  --image-failures .data/collection-20261025-01/audit/image-download-failures/products `
  --output .data/collection-20261025-01/product-import.sql

# 3) 로컬 Compose QA
python -X utf8 scripts/load_local_products.py --run-dir .data/collection-20261025-01
```

- `status.json`의 `state=succeeded`, `product_count=3000`과 `manifest.json` SHA-256을 검증한다.
- 동일 `product_id` / `source_option_id`는 upsert라 재실행해도 중복 insert가 나지 않는다.
- 이미지 inventory가 있으면 S3 object key를 `image_url`에 넣는다. 공개 URL은 product-service Presigned GET으로 만든다.
- 이미지 다운로드 실패 audit(가이드 기준 64건)은 적재를 중단하지 않는다.
- 상품 JSON 적재 후 object key로 바꾸려면 `images/products/*/manifest.json`만 sync한 뒤
  `scripts/render_product_image_s3_key_update.py`로 remap SQL을 만들어 적용한다.
- Compose `postgres`만 대상으로 하므로 **RDS에는 닿지 않는다**. 운영 반영은 렌더된 SQL을 private EKS 네트워크의 단기 pod에서 `product_service_app`로 실행한다.

## 크롤링 리뷰 (로컬 QA)

무신사에서 수집한 리뷰(500개 상품, 약 3.5만 건)를 로컬 Compose DB에 넣어 상품 상세 후기 탭을 실제 데이터로 확인할 때 쓴다.
원본 JSON은 Git에 넣지 않는다. 크롤링 담당에게 받거나 S3 `pipeline/runs/<run-id>/reviews/`에서 받아 `data/` 폴더와 `report.json`을 그대로 둔다(기본 위치 `.data/review-crawl-500-20261022/`).

```powershell
docker compose up -d --build
python scripts/load_local_reviews.py --input .data/review-crawl-500-20261022/data
```

- review-service가 healthy가 되고 Flyway가 `review_service.reviews`(V2)를 만들 때까지 최대 3분 기다린 뒤 적재한다. 그 전에 실행해도 된다.
- SQL은 `docker compose exec`로 psql 표준 입력에 바로 보내 디스크에 남기지 않는다. PowerShell 따옴표·한글 인코딩 문제를 피하려고 셸 파이프를 쓰지 않는다.
- `(source, source_review_id)` 기준 upsert라 다시 실행해도 중복되지 않는다.
- 마지막에 DB의 MUSINSA 리뷰 수와 Gateway(`/api/v1/reviews`) 응답을 확인해 JSON으로 출력한다. Gateway가 새로 뜬 review-service를 찾기까지 1분 정도 503이 날 수 있어 그동안 재시도한다.
- 형식이 잘못된 리뷰(빈 본문 등)는 건너뛰고 개수와 이유를 출력한다. 하나라도 있으면 실패시키려면 `--strict`를 붙인다.
- Compose의 `postgres` 컨테이너에만 접속하므로 운영 DB에는 닿지 않는다. 운영 적재는 [infra/data-pipeline/README.md](../data-pipeline/README.md) 절차를 따른다.

**오래된 로컬 DB:** Flyway 도입 전(`ddl-auto: update`)부터 쓰던 볼륨이면 review-service가 `Schema-validation: missing column [feedback_claimed_at] in table [size_surveys]`로 뜨지 않는다. 기존 테이블을 baseline(V1)으로 보고 V2만 실행해서 V1에 있는 컬럼이 빠지기 때문이다. 스크립트가 이 상태를 감지하면 적재 전에 멈추고 안내한다. 이때 로컬 review 스키마를 비우고 다시 만든다(기존 소유자는 유지하며, 로컬 리뷰·사이즈 설문 데이터는 지워진다).

```powershell
python scripts/load_local_reviews.py --input .data/review-crawl-500-20261022/data --reset-review-schema
```

**FE에서 확인:** 프론트 저장소에서 `.env.local`에 `VITE_ENABLE_MOCKING=false`를 넣고 `VITE_API_BASE_URL`은 비워 둔 채(`http://localhost:8080/api/v1`) `npm run dev`로 실행한다. 목업이 켜져 있으면 실제 리뷰 대신 같은 문구의 가짜 후기 13개가 보인다.
