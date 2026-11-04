# Fitzza 백엔드 상세

루트 [README.md](../README.md)의 빠른 시작을 기준으로, 인증·서비스 간 호출·도메인 연동·DB·관측성 설명을 가독성 있게 정리한 문서입니다. 내용은 기존 README에 있던 설명을 주제별로 나눈 것입니다.

## 목차

1. [인증·인가](#인증인가)
2. [서비스 간 토큰](#서비스-간-토큰)
3. [Gateway·포트·경로](#gateway포트경로)
4. [커뮤니티·알림·설문](#커뮤니티알림설문)
5. [VTON](#vton)
6. [로컬 확인·Swagger](#로컬-확인swagger)
7. [DB](#db)
8. [Prometheus 메트릭](#prometheus-메트릭)
9. [Refresh Token 쿠키](#refresh-token-쿠키)

---

## 인증·인가

### JWT / CORS

| 항목 | 설명 |
| --- | --- |
| `JWT_SECRET` | user-service가 Access Token을 서명하고 gateway-service가 검증. 32바이트 이상, 필수. 없으면 Compose 시작 실패. `.env.example`에 비밀값 없음 |
| Access Token | `Authorization: Bearer …` |
| Refresh Token | HttpOnly 쿠키. Redis에 저장. JSON 본문으로 주고받지 않음 |
| 만료 | `JWT_ACCESS_EXPIRATION_SECONDS`(1~900, 기본 15분), `JWT_REFRESH_EXPIRATION_SECONDS`(기본 30일) |
| CORS | `CORS_ALLOWED_ORIGINS`(기본 `http://localhost:3000,http://localhost:5173`). 목록 외 브라우저는 403 |

공개(토큰 없이): `POST /api/auth/signup|signin|refresh|signout`(및 `/api/v1/auth/...`).  
회원가입에서 이메일·닉네임 중복 시 409 `DUPLICATE_VALUE`와 `errors` 배열.  
그 외 사용자 API·추천 API(`/api/v1/recommendations/**`)는 Access Token 필요. 실패 시 Gateway 401.

로그아웃은 Refresh를 Redis에서 지우고 쿠키를 만료합니다. `Authorization`을 같이 보내면 Access도 블랙리스트에 올리고, Gateway는 블랙리스트 토큰을 401 `INVALID_TOKEN`으로 거부합니다. Redis 조회 실패 시 토큰 요청은 503 `AUTH_UNAVAILABLE`.

### 사용자 역할 (USER / ADMIN)

- `users.role` (`USER`·`ADMIN`, 기본 `USER`, 이슈 #225)
- Access Token `role` 클레임 → Gateway가 `X-User-Role`로 전달. 클라이언트가 보낸 `X-User-Role`은 항상 제거
- `role` 없는 예전 토큰·모르는 값은 `USER`
- 로그인·`GET /api/users/me` 응답에 `role` 포함. FE는 메뉴 표시만, 권한 검사는 서버
- 관리자 지정 API 없음. 운영 DB에서 지정 후 재로그인

```sql
UPDATE user_service.users SET role = 'ADMIN' WHERE email = '<관리자 이메일>';
```

### 요청 ID

Gateway가 `X-Request-Id`를 정해 전달·응답 헤더에 담습니다(영문·숫자·`._-` 8~64자면 클라이언트 값 유지). user·community·notification은 로그에 `[요청 ID]`로 찍습니다. 문의 시 `docker compose logs | grep <ID>`.

---

## 서비스 간 토큰

서비스끼리 호출하는 API는 `/api` 없이 시작하고 Gateway 라우트가 없습니다. 호출 측이 `X-Service-Token`을 보내고, 수신 측이 허용 목록을 검사합니다. 없거나 불허면 401 `UNAUTHENTICATED`. 현재 요청의 `X-User-Id`는 다른 서비스로 그대로 전달합니다. Gateway는 클라이언트가 보낸 `X-Service-Token`·`X-Internal-Token`을 전달 전에 제거합니다.

| 토큰 | 보내는 서비스 | 호출할 수 있는 API |
| --- | --- | --- |
| `COMMUNITY_SERVICE_TOKEN` | community-service | user `GET /users`(닉네임), notification `POST /notifications/events`, product `GET /products`, `GET /wishlists/check`, `GET /worldcups/{id}`, 추천 `GET /recommendations/combos/{id}`, 가상 피팅 `GET /fittings/{id}` |
| `ORDER_SERVICE_TOKEN` | order-service | product `GET /product-options` |
| `RECOMMENDATION_SERVICE_TOKEN` | recommendation-service | user `GET /users/{userId}/body`, notification `POST /notifications/events`(`RECOMMENDATION_DONE`, targetId=추천 요청 ID), product `GET /products/measurements` |
| `VTON_SERVICE_TOKEN` | 가상 피팅 서비스 | notification `POST /notifications/events` |
| `PRODUCT_SERVICE_TOKEN` | product-service | 타 서비스 호출용(호출 붙이기 전에는 비워 둠) |
| `REVIEW_SERVICE_TOKEN` | review-service | order `GET /order-items/{orderItemId}`, 추천 `POST /recommendations/size-feedback` |

기동 제약:

- `COMMUNITY_SERVICE_TOKEN` 미설정/짧음 → user·notification·community·product 기동 실패
- `ORDER_SERVICE_TOKEN` 미설정/짧음 → order·product 기동 실패
- `REVIEW_SERVICE_TOKEN` 미설정/짧음 → order 기동 실패  
나머지 토큰은 해당 서비스가 호출을 시작할 때 설정합니다.

---

## Gateway·포트·경로

- Gateway는 전달 요청에서 클라이언트의 `X-User-Id`를 제거하고, 보호된 API에서는 검증한 JWT subject로 설정합니다.
- user(8081)·product(8082)·order(8083)·community(8084)·review(8085)·notification(8086)은 호스트에 공개하지 않습니다. 이 서비스들은 `X-User-Id`를 로그인 사용자로 믿기 때문입니다.
- 공개 호출 예: 상품 `http://localhost:8080/api/products`(또는 `/api/v1/products`), 장바구니 `/api/carts`, 커뮤니티 `/api/community/...`, 알림 `/api/notifications`
- FE는 `/api/v1/**`, Swagger·기존 도구는 `/api/**`. Gateway가 Java 서비스로 넘기기 전에 `/api/v1` → `/api`. 가상 피팅·추천은 서비스가 이미 `/api/v1`을 쓰므로 바꾸지 않습니다.
- 서비스 간 알림 호출: Compose 네트워크 `http://notification-service:8086`

운영 Gateway는 `SPRING_PROFILES_ACTIVE=prod`에서 `/api-docs/**`·Swagger UI를 끕니다. 서비스 직접 문서도 끄려면 `SPRINGDOC_API_DOCS_ENABLED=false`, `SPRINGDOC_SWAGGER_UI_ENABLED=false`. Compose `.env`만으로 프로파일이 전달되지 않으므로 배포 설정에서 Gateway 환경 변수로 지정합니다.

---

## 커뮤니티·알림·설문

### 공유 글

`POST /api/community/posts`의 `sharedType`·`sharedId`: `WORLDCUP` / `COMBO` / `FITTING`.  
저장 전 각각 product `GET /worldcups/{id}`, 추천 `GET /recommendations/combos/{id}`, 가상 피팅 `GET /fittings/{id}`로 본인 결과인지 확인하고 스냅샷 저장.

| 상황 | 코드 |
| --- | --- |
| 남의 결과 | 403 `NOT_SHARED_OWNER` |
| 미완료 피팅 | 409 `SHARED_TARGET_NOT_READY` |
| 남의 AI 코디 선택지 | 403 `NOT_RECOMMENDED_ITEM` |
| 추천/피팅 조회 불가 | 503 `SHARE_LOOKUP_UNAVAILABLE` / `RECOMMENDATION_LOOKUP_UNAVAILABLE` |

AI 추천 단품은 받은 추천인지 확인할 API가 없어 상품 존재만 확인합니다. 추천·피팅은 Eureka 미등록이라 `RECOMMENDATION_SERVICE_URL`, `VTON_SERVICE_URL`로 호출합니다.

### 댓글 Jev 판정

투표 댓글·답글 저장/수정 후 TypeSafe Jev가 선택지 지지 여부를 판정합니다(`JEV_SUPPORT_THRESHOLD` 기본 0.6 → `supportedOptionId`).  
목록은 `?supportedOptionId=` 필터, 투표 결과의 `supportCommentCount`는 선택지별 추천 댓글 수.  
`TYPESAFE_API_KEY` 없거나 Jev 실패 시 판정만 건너뛰고 댓글은 성공합니다.

### 투표 마감 알림

1분마다(`fitzza.vote.close-check-delay-ms`, 기본 60000) 마감 처리 후 작성자에게 `VOTE_CLOSED`. 조기 종료에는 알림 없음. 실패분은 다음 주기에 재시도(실패 글은 뒤로 밀림).

### 인앱 알림·FCM

- 사용자 API: `GET /api/notifications`, `PATCH /api/notifications/{notificationId}` (본인만)
- 생성: `POST /notifications/events` (동일 `eventId`는 한 번만 저장)
- 댓글 알림: 저장 확정 후 별도 스레드. 알림 서비스 장애 시 댓글은 성공(경고 로그만)
- 기기 토큰: `POST`/`DELETE /api/notifications/tokens` Body `{ "token": "..." }`
- 푸시 유형: `COMMENT`, `VOTE_CLOSED`, `FITTING_DONE`·`FITTING_FAILED`, `RECOMMENDATION_DONE`
- 추천은 성공·실패 모두 `RECOMMENDATION_DONE`. 결과는 푸시에 없고 `GET /api/v1/recommendations/{requestId}`가 최종
- `FIREBASE_CREDENTIALS` 없으면 푸시 생략. 푸시 실패해도 인앱 알림 유지. `UNREGISTERED`·`SENDER_ID_MISMATCH` 토큰 삭제

### 사이즈 설문

`POST /api/surveys` 저장 후 review-service가 `POST /recommendations/size-feedback`으로 전달합니다.  
추천 장애여도 설문은 성공, 5분마다(`fitzza.size-feedback.retry-delay-ms`) 재시도. URL/토큰 비어 있으면 보내지 않음.

recommendation-service는 피드백을 사용자·subcategory·핏별 선호 실측(`user_size_preferences`)에 지수 이동평균(새 값 30%)으로 합칩니다. SMALL/BIG은 같은 상품의 한 단계 위/아래 사이즈 실측과의 중간값으로 반영합니다.

### 사이즈 추천 적합도 안내

`GET /recommendations/{productId}/size`와 추천 결과의 `fitPercent`에 따라 `evidence` 문구가 달라집니다. 기준은 recommendation-service 환경 변수로 조정합니다.

| 변수 | 기본값 | 의미 |
| --- | --- | --- |
| `SIZE_FIT_GOOD_THRESHOLD` | `70` | 이 값 이상이면 기준 출처 기본 문구만 안내 |
| `SIZE_FIT_LOW_THRESHOLD` | `40` | GOOD 미만·LOW 이상이면 가장 어긋나는 핵심 항목 안내, LOW 미만이면 사이즈 범위 방향(가장 큰/작은 사이즈도 맞지 않음, 핏 차이) 안내 |

추천 사이즈와 `fitPercent`는 구간과 관계없이 항상 내려갑니다.

---

## VTON

```bash
docker compose up --build -d vton-service vton-worker
```

워커는 `python -m app.worker`, HTTP 포트 없음. `.env`에서 `VTON_QUEUE_BACKEND=sqs`, `VTON_STORAGE_BACKEND=s3`와 LocalStack 주소를 맞춥니다. API·워커가 분리되어 이미지는 공통 S3를 써야 합니다. `memory` 큐는 API 내부 처리라 워커로 안 넘깁니다.

---

## 로컬 확인·Swagger

```powershell
.\scripts\health-check.ps1
```

- 상태는 컨테이너에 직접 `GET /health` (Gateway는 `/health`를 프록시하지 않음)
- 정상: `200` + `{"status":"UP","liveness":"UP","readiness":"UP"}` / 미준비: `503` + `NOT_READY`
- Eureka <http://localhost:8761>, LocalStack <http://localhost:4566/_localstack/health>
- Jaeger <http://localhost:16686> — Compose 샘플링 `1.0`, OTLP `http://jaeger:4318/v1/traces`. yml 기본 샘플링 `0.0`. 운영에서 켤 때 `MANAGEMENT_TRACING_SAMPLING_PROBABILITY`와 `MANAGEMENT_OTLP_TRACING_ENDPOINT`를 함께 설정. config·discovery는 추적 제외
- Swagger: <http://localhost:8080/swagger-ui.html> (`Authorize`에 Access Token). `/api`로 시작하지 않는 API는 이 화면에서 호출되지 않음

```bash
curl -H "Authorization: Bearer <access-token>" http://localhost:8080/api/users/me
curl -H "Authorization: Bearer <access-token>" http://localhost:8080/api/v1/users/me
curl http://localhost:8080/api-docs/user-service
curl http://localhost:8080/api/products
curl http://localhost:8080/api/v1/products
curl -X POST http://localhost:8080/api/v1/recommendations \
  -H 'Authorization: Bearer <access-token>' \
  -H 'Content-Type: application/json' \
  -d '{"user_id":"00000000-0000-0000-0000-000000000001","limit":10}'
```

---

## DB

### 서비스별 계정

Java 6개 서비스는 `<스키마>_app`(예: `user_service_app`)으로만 접속합니다. 자기 스키마 소유자이며 타 스키마 접근 불가. 공용 `POSTGRES_USER` fallback 없음.

- 앱: `USER_SERVICE_DB_USER` / `USER_SERVICE_DB_PASSWORD` 등 서비스별 필수
- K8s: `fitzza-db-secrets`에 12개 키. 형식은 `infra/k8s/base/db-secret.example.yaml`
- 계정 생성: 관리자로 `infra/postgres/service-accounts.sql` 실행(psql 15+). 비밀번호 env 없는 서비스는 건너뜀

```bash
psql -v ON_ERROR_STOP=1 -U <관리자> -d fitzza -f infra/postgres/service-accounts.sql
```

### Flyway

Java 6개 서비스(user·product·order·community·review·notification)는 `db/migration` + `ddl-auto: validate`입니다(설정은 config-service). `infra/postgres/init.sql`은 스키마만 만듭니다.

1. 버전: `V1__`, `V2__` … (동시 작업 시 슬랙에 번호 공유)
2. baseline-on-migrate: 기존 DB는 V1을 다시 실행하지 않음
3. 머지된 SQL은 수정하지 말고 새 버전 추가

### 기존 user DB 업그레이드

유니크 제약 이름을 `uk_users_email`, `uk_users_nickname`으로 맞춥니다. 성별 코드 `W`→`F`:

```sql
ALTER TABLE user_service.user_body DROP CONSTRAINT IF EXISTS user_body_gender_check;
UPDATE user_service.user_body SET gender = 'F' WHERE gender = 'W';
```

체형(`body_type`) 컬럼은 미사용이며 남아 있어도 동작에 영향 없습니다.

스키마 다이어그램: [docs/erd/README.md](erd/README.md)

---

## Prometheus 메트릭

일반 API 포트가 아니라 **관리 포트**만 메트릭을 엽니다. Gateway/Ingress의 `http` 포트로는 라우팅하지 않습니다.

| 서비스 | API 포트 | 관리(메트릭) 포트 |
| --- | ---: | ---: |
| gateway-service | 8080 | 9080 `/actuator/prometheus` |
| user-service | 8081 | 9081 |
| product-service | 8082 | 9082 |
| order-service | 8083 | 9083 |
| community-service | 8084 | 9084 |
| review-service | 8085 | 9085 |
| notification-service | 8086 | 9086 |
| vton-service (FastAPI) | 8000 (로컬 8091) | 9091 `/metrics` |
| recommendation-service (FastAPI) | 8000 (로컬 8092) | 9092 `/metrics` |

- 포트 변경: `MANAGEMENT_SERVER_PORT` (`0`이면 FastAPI 메트릭 서버 미기동)
- 주요 지표: `http_server_requests_seconds_count`, `http_server_requests_seconds_bucket`, JVM/HikariCP 관련 지표
- 라벨: `application`, `method`, `uri`(경로 템플릿), `status`, `outcome`, `exception`만. 사용자/상품/요청 ID·토큰·쿼리는 라벨에 넣지 않음
- 지연 버킷은 config-service 공통 설정에 고정. 메트릭은 Jaeger 샘플링과 무관하게 항상 동작. `vton-worker`는 HTTP 없어 제외
- 수집·대시보드: [infra/aws/observability/README.md](../infra/aws/observability/README.md), [infra/k8s/observability/prometheus/README.md](../infra/k8s/observability/prometheus/README.md)

```bash
docker run --rm --network fitzza_default curlimages/curl:8.10.1 -s http://community-service:9084/actuator/prometheus | grep http_server_requests_seconds_count
docker run --rm --network fitzza_default curlimages/curl:8.10.1 -s http://recommendation-service:9092/metrics | grep http_server_requests_seconds_count
```

---

## Refresh Token 쿠키

로그인(`POST /api/auth/signin`) 응답: `{ "accessToken", "userId", "nickname", "role" }`.  
Refresh는 `Set-Cookie: refreshToken=...; Path=/api; HttpOnly; SameSite=Lax`로만 전달합니다.

| API | 동작 |
| --- | --- |
| `POST /api/auth/refresh` | 쿠키 포함, 본문 없음 → `{ "accessToken" }` + 새 Refresh 쿠키(이전 Refresh 재사용 불가) |
| `POST /api/auth/signout` | 쿠키 포함, 본문 없음 → Refresh 폐기·쿠키 삭제. Bearer 있으면 Access도 폐기 |
| 쿠키 없음/빈 값 | 400 `INVALID_REQUEST` |
| 유효하지 않은 Refresh | 401 `INVALID_REFRESH_TOKEN` |

`/api/v1/auth/...`에서도 동일합니다. 브라우저는 `credentials: 'include'`(또는 Axios `withCredentials: true`) 필요. `CORS_ALLOWED_ORIGINS`에만 쿠키 허용(`*` 금지). `SameSite=Lax`라 FE와 API는 같은 사이트여야 합니다.

- 쿠키 유효기간 = `JWT_REFRESH_EXPIRATION_SECONDS`(기본 30일), Redis와 동일
- `REFRESH_COOKIE_SECURE`: 로컬 HTTP는 false, 운영 HTTPS는 true
