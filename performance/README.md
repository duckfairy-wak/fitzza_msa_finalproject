# k6 테스트 실행

## 로컬 k6로 실행

k6를 설치하고, 백엔드가 실행된 상태에서 저장소 루트에서 실행합니다. 아래 예시는 PowerShell 기준입니다.
로컬 k6는 `.env`를 자동으로 읽지 않습니다.

```powershell
# 조회 부하 테스트
k6 run -e BASE_URL=http://localhost:8080 -e PROFILE=public -e VUS=1 -e DURATION_SECONDS=10 performance/simple-api-load-test.js

# 구매 시나리오
k6 run -e BASE_URL=http://localhost:8080 -e VUS=1 -e ITERATIONS=1 performance/scenario-order-checkout.js
```

회원 조회·추천·가상피팅에는 테스트 계정의 유효한 토큰을 `Bearer ` 접두사 없이 설정합니다.

```powershell
$env:ACCESS_TOKEN = '<테스트 계정 access token>'

# 회원 API 조회
k6 run -e BASE_URL=http://localhost:8080 -e PROFILE=member -e VUS=1 -e DURATION_SECONDS=10 performance/simple-api-load-test.js

# AI 스타일리스트 추천
k6 run -e BASE_URL=http://localhost:8080 -e VUS=1 -e ITERATIONS=1 performance/scenario-recommendation.js

# 가상피팅: 사진·상품 ID는 실제 값으로 교체
k6 run -e BASE_URL=http://localhost:8080 -e VUS=1 -e ITERATIONS=1 -e PHOTO_ID=123 -e PRODUCT_IDS=101,201 performance/scenario-vton.js
```

`PHOTO_ID`는 해당 계정 소유의 사진 ID이며, `PRODUCT_IDS`는 서로 다른 카테고리의 피팅 가능한 상품 ID 2~5개입니다.

## Docker Compose로 실행

k6를 별도로 설치하지 않아도 됩니다. `.env.example`을 참고해 Compose 환경 변수를 준비하고 저장소 루트에서 실행합니다.

```powershell
# 백엔드 실행
docker compose up --build -d

# 기본 조회 부하 테스트
docker compose run --rm -e VUS=1 -e DURATION_SECONDS=10 k6

# 구매 시나리오
docker compose run --rm k6 run -e BASE_URL=http://gateway-service:8080 -e VUS=1 -e ITERATIONS=1 /scripts/scenario-order-checkout.js
```

기본 실행은 `simple-api-load-test.js`입니다. 다른 스크립트는 `k6 run /scripts/<파일명>`으로 지정합니다.
컨테이너에서 백엔드에 접근할 때는 `localhost` 대신 `http://gateway-service:8080`을 사용합니다.

Compose는 `.env`의 `K6_BASE_URL`, `K6_PROFILE`, `K6_VUS`, `K6_DURATION_SECONDS`, `K6_P95_MS`, `K6_ACCESS_TOKEN`을 전달합니다.
PowerShell의 토큰을 직접 전달하려면 다음처럼 실행합니다.

```powershell
$env:ACCESS_TOKEN = '<테스트 계정 access token>'

# 회원 API 조회
docker compose run --rm -e ACCESS_TOKEN k6 run -e PROFILE=member -e VUS=1 -e DURATION_SECONDS=10 /scripts/simple-api-load-test.js

# AI 스타일리스트 추천
docker compose run --rm -e ACCESS_TOKEN k6 run -e VUS=1 -e ITERATIONS=1 /scripts/scenario-recommendation.js

# 가상피팅: 사진·상품 ID는 실제 값으로 교체
docker compose run --rm -e ACCESS_TOKEN k6 run -e VUS=1 -e ITERATIONS=1 -e PHOTO_ID=123 -e PRODUCT_IDS=101,201 /scripts/scenario-vton.js
```
