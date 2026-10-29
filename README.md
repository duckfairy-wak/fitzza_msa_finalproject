# Fitzza MSA Backend

Fitzza 패션 커머스의 최소 실행형 MSA 골격입니다. 각 서비스는 독립 배포 단위이며, 현재는 상태 확인용 API와 인프라 연결 설정까지만 제공합니다.

팀 브랜치·커밋·PR·코드 규칙은 [CONTRIBUTING.md](CONTRIBUTING.md)를 따릅니다. AI 코딩 도구는 작업 전에 [AGENTS.md](AGENTS.md)를 먼저 확인해야 합니다.

## 구성

| 영역 | 서비스 | 포트 |
| --- | --- | ---: |
| Platform | Config Server | 8888 |
| Platform | Eureka Discovery | 8761 |
| Edge | API Gateway | 8080 |
| Commerce | User / Product / Order / Community / Review | 8081-8085 |
| Messaging | Notification | 8086 |
| AI | Virtual Try-On / Recommendation (FastAPI) | 8091-8092 |
| Infra | PostgreSQL / Redis / LocalStack(S3, SQS) / Qdrant | 5432 / 6379 / 4566 / 6333 |
| Observability | Jaeger (UI / OTLP HTTP) | 16686 / 4318 |

## 빠른 시작

요구 사항: Docker Desktop 및 Docker Compose

```bash
cp .env.example .env
# .env의 JWT_SECRET, COMMUNITY_SERVICE_TOKEN, ORDER_SERVICE_TOKEN에 서로 다른 32바이트 이상의 무작위 비밀값을 입력한 뒤 실행합니다.
docker compose up --build -d
```

Windows PowerShell에서는 `Copy-Item .env.example .env`를 사용합니다.

VTON API와 SQS 워커는 `docker compose up --build -d vton-service vton-worker`로 실행합니다. 두 서비스는 각각 빌드·의존성을 정의하고 서비스 URL·PostgreSQL·Redis·AWS 환경변수 확장 필드를 직접 참조하며, 워커는 `python -m app.worker`로 실행하고 HTTP 포트를 공개하지 않습니다. 기존 `.env`를 사용할 때는 `VTON_QUEUE_BACKEND`를 `sqs`, `VTON_STORAGE_BACKEND`를 `s3`로 설정하고 큐·DLQ 주소를 `.env.example`의 LocalStack 주소에 맞추세요. API와 워커가 서로 다른 컨테이너이므로 이미지는 공통 S3 저장소를 사용해야 합니다. `memory` 큐 모드는 API 내부에서 처리하며 별도 워커에 작업을 전달하지 않습니다.

Config Server 주소 환경변수는 `CONFIG_SERVICE_URL`입니다. Compose와 Kubernetes에서는 `http://config-service:8888`을 주입하며, IDE에서 직접 실행할 때는 기본값 `http://localhost:8888`을 사용합니다. 직접 실행 시 주소를 변경하려면 실행 설정의 환경변수에 지정합니다.

서비스 디스커버리 주소 환경변수는 `DISCOVERY_SERVICE_URL`입니다. Compose와 Kubernetes에서는 `http://discovery-service:8761/eureka/`를 주입하며, IDE에서 직접 실행할 때는 기본값 `http://localhost:8761/eureka/`를 사용합니다. 직접 실행 시 `.env`는 자동으로 로드되지 않으므로 주소 변경이 필요하면 실행 설정의 환경변수에 지정합니다.

`JWT_SECRET`은 user-service가 Access Token을 서명하고 gateway-service가 검증하는 데 함께 쓰는 32바이트 이상 문자열입니다. 로컬과 배포 환경 모두 `.env` 또는 환경 변수로 직접 설정해야 합니다. 값이 없거나 비어 있으면 Docker Compose가 시작되지 않습니다. `.env.example`에는 비밀값을 제공하지 않습니다.

서비스끼리 호출하는 API는 `/api` 없이 시작하며(예: user-service `GET /users`, product-service `GET /products`, `GET /product-options`, order-service `GET /order-items/{orderItemId}`, notification-service `POST /notifications/events`) Gateway 라우트가 없습니다. Gateway에 `/api`로 시작하지 않는 라우트를 추가하지 않습니다. 호출하는 서비스는 자기 토큰을 `X-Service-Token` 헤더로 보내고, 받는 서비스는 API마다 허용한 서비스의 토큰인지 확인합니다. 현재 요청의 `X-User-Id`는 다른 서비스로 그대로 전달합니다. 토큰은 서비스마다 다른 32바이트 이상 값입니다.

| 토큰 | 보내는 서비스 | 호출할 수 있는 API |
| --- | --- | --- |
| `COMMUNITY_SERVICE_TOKEN` | community-service | user `GET /users`(닉네임), notification `POST /notifications/events`, product `GET /products`, `GET /wishlists/check`, `GET /worldcups/{id}`, 추천 `GET /recommendations/combos/{id}`, 가상 피팅 `GET /fittings/{id}` |
| `ORDER_SERVICE_TOKEN` | order-service | product `GET /product-options` |
| `RECOMMENDATION_SERVICE_TOKEN` | recommendation-service | user `GET /users/{userId}/body`(신체 정보), notification `POST /notifications/events`(추천 처리 완료 `RECOMMENDATION_DONE`, 성공·실패 모두 이 유형이고 targetId는 추천 요청 ID), product `GET /products/measurements` |
| `VTON_SERVICE_TOKEN` | 가상 피팅 서비스 | notification `POST /notifications/events` |
| `PRODUCT_SERVICE_TOKEN` | product-service | product-service가 다른 서비스를 호출할 때 보내는 토큰. 호출을 붙이기 전에는 비워 둔다. |
| `REVIEW_SERVICE_TOKEN` | review-service | order `GET /order-items/{orderItemId}`(리뷰·설문 작성 전 본인 주문 확인), 추천 `POST /recommendations/size-feedback`(사이즈 설문 결과 전달) |

`COMMUNITY_SERVICE_TOKEN`이 없거나 32바이트보다 짧으면 user·notification·community·product-service가 시작되지 않습니다. `ORDER_SERVICE_TOKEN`이 없거나 짧으면 order-service와 product-service가 시작되지 않습니다. `REVIEW_SERVICE_TOKEN`이 없거나 짧으면 order-service가 시작되지 않습니다. 나머지 토큰은 해당 서비스가 호출을 시작할 때 설정합니다. 토큰이 없거나 허용되지 않은 서비스의 토큰이면 HTTP 401 `UNAUTHENTICATED`를 반환합니다. Gateway는 클라이언트가 보낸 `X-Service-Token`과 `X-Internal-Token`을 전달하기 전에 제거합니다.

커뮤니티 공유 글(`POST /api/community/posts`의 `sharedType`·`sharedId`)은 월드컵 결과(`WORLDCUP`), 추천 코디(`COMBO`), 가상 피팅 결과(`FITTING`)를 받습니다. community-service는 글을 저장하기 전에 각각 product-service `GET /worldcups/{id}`, 추천 서비스 `GET /recommendations/combos/{id}`, 가상 피팅 서비스 `GET /fittings/{id}`로 본인 결과인지 확인하고 공유 당시 모습을 스냅샷으로 저장합니다. 남의 결과는 403 `NOT_SHARED_OWNER`, 완료되지 않은 피팅은 409 `SHARED_TARGET_NOT_READY`입니다. 투표 선택지 중 AI 추천 코디도 추천 서비스로 본인이 받은 코디인지 확인합니다(남의 코디는 403 `NOT_RECOMMENDED_ITEM`). AI 추천 단품은 받은 추천인지 확인할 API가 없어 상품이 있는지만 확인합니다. 추천·피팅 서비스는 Eureka에 등록되지 않은 FastAPI라 `RECOMMENDATION_SERVICE_URL`, `VTON_SERVICE_URL` 주소로 부르며, 값이 비어 있거나 서비스가 응답하지 않으면 해당 공유·선택지만 503(`SHARE_LOOKUP_UNAVAILABLE`, `RECOMMENDATION_LOOKUP_UNAVAILABLE`)이고 나머지 기능은 그대로 동작합니다.

user-service의 8081 포트와 notification-service의 8086 포트는 호스트에 공개하지 않습니다.

브라우저에서 Gateway를 호출할 FE 주소는 `CORS_ALLOWED_ORIGINS`(쉼표로 구분, 기본 `http://localhost:3000,http://localhost:5173`)로 정합니다. 목록에 없는 주소에서 온 브라우저 요청은 403으로 거부됩니다. 허용한 주소에서는 쿠키를 포함한 요청을 보낼 수 있습니다. Access Token은 `Authorization` 헤더로, Refresh Token은 HttpOnly 쿠키로 전달합니다.

토큰 유효기간은 `JWT_ACCESS_EXPIRATION_SECONDS`(Access Token, 1~900초, 기본 15분)와 `JWT_REFRESH_EXPIRATION_SECONDS`(Refresh Token, 기본 30일)로 바꿀 수 있습니다. Refresh Token은 Redis에 저장합니다.

로그아웃(`POST /api/auth/signout`)은 쿠키의 Refresh Token을 Redis에서 지우고 쿠키를 만료시킵니다. `Authorization: Bearer <access-token>` 헤더를 함께 보내면 그 Access Token도 남은 만료 시간 동안 Redis 블랙리스트에 올라가고, Gateway는 블랙리스트에 있는 토큰을 401 `INVALID_TOKEN`으로 거부합니다. Gateway가 Redis를 조회하지 못하면 토큰이 실린 요청은 503 `AUTH_UNAVAILABLE`로 응답합니다.

투표글에 댓글·답글이 저장되거나 수정되면 community-service가 커밋 뒤 별도 스레드에서 TypeSafe Jev에 "이 댓글이 어느 선택지를 추천하는지"를 묻습니다(보기: 선택지 라벨 A~D와 `none`). 고른 선택지의 확신이 `JEV_SUPPORT_THRESHOLD`(기본 0.6) 이상이면 댓글의 `supportedOptionId`에 저장하고, 아니면 null로 둡니다. 댓글 목록은 `supportedOptionId`를 함께 내려주고 `?supportedOptionId=`로 그 선택지를 추천한 댓글만 볼 수 있으며, 투표 결과(`GET /api/community/posts/{postId}/poll`)의 `supportCommentCount`는 선택지별 추천 댓글 수입니다. 댓글을 수정하면 판정을 지우고 다시 판정하며, 투표 선택지를 바꾸면 그 글의 댓글을 모두 다시 판정합니다. `TYPESAFE_API_KEY`가 비어 있거나 Jev가 응답하지 않으면 판정만 건너뛰고 댓글 작성·수정은 그대로 성공합니다.

알림 API(`GET /api/notifications`, `PATCH /api/notifications/{notificationId}`)는 로그인한 사용자의 알림만 다룹니다. 알림은 다른 서비스가 `POST /notifications/events`로 보낸 이벤트로 만들어지며, 같은 `eventId`로 다시 보내도 한 번만 저장됩니다. 다른 사람이 내 게시글에 댓글이나 답글을 달면 community-service가 댓글 저장이 확정된 뒤 별도 스레드에서 알림을 보냅니다. 알림 서비스가 꺼져 있으면 경고 로그만 남기고 댓글 작성은 그대로 성공합니다. 투표는 community-service가 1분마다(`fitzza.vote.close-check-delay-ms`, 기본 60000) 마감 시각이 지난 글을 찾아 마감 처리하고, 작성자에게 `VOTE_CLOSED` 알림을 보냅니다. 알림 서비스가 꺼져 있어 보내지 못한 알림은 다음 실행에서 성공할 때까지 다시 보냅니다. 실패한 글은 재시도 순서가 뒤로 밀려 새로 마감된 투표의 알림을 막지 않습니다. 작성자가 직접 조기 종료한 투표에는 알림을 보내지 않습니다.

푸시 알림(FCM)은 FE가 Firebase에서 받은 기기 토큰을 `POST /api/notifications/tokens`(Body: `{ "token": "..." }`)로 등록하면 받을 수 있습니다. 한 사용자가 여러 기기를 등록할 수 있고, 같은 토큰을 다시 등록해도 결과는 같으며, 다른 계정에 있던 토큰이면 새 계정으로 옮깁니다. 로그아웃 전에는 `DELETE /api/notifications/tokens`(같은 Body)로 해제합니다. 알림이 새로 저장되면(댓글 `COMMENT`, 투표 마감 `VOTE_CLOSED`, 가상 피팅 `FITTING_DONE`·`FITTING_FAILED`, 추천 결과 `RECOMMENDATION_DONE`) 저장이 확정된 뒤 별도 스레드에서 그 사용자의 모든 기기로 푸시를 보냅니다(제목 `FITZZA`, 본문은 알림 내용, data에 `notificationId`·`type`·`targetId`). 같은 `eventId`로 다시 온 이벤트에는 푸시를 다시 보내지 않습니다. 추천 결과 알림은 성공·실패와 관계없이 `RECOMMENDATION_DONE` 하나만 쓰며, 결과 자체는 푸시에 담지 않고 FE가 `GET /api/v1/recommendations/{requestId}`의 `status`·`message`로 확인합니다(푸시는 끝났다는 신호이고 상태 API가 최종 기준). FCM이 더는 쓸 수 없다고 알려준 토큰(`UNREGISTERED`·`SENDER_ID_MISMATCH`)은 지웁니다. 푸시 전송이 실패해도 알림은 저장된 그대로 남아 알림 목록에서 볼 수 있습니다. `FIREBASE_CREDENTIALS`(서비스 계정 키 JSON의 base64 값, 배포 비밀 저장소에는 JSON 그대로도 가능)가 비어 있으면 푸시를 보내지 않고 로그만 남깁니다.

사이즈 설문(`POST /api/surveys`)이 저장되면 review-service가 저장이 확정된 뒤 별도 스레드에서 추천 서비스 `POST /recommendations/size-feedback`(Body: `userId`, `productId`, `optionId`, `sizeFeedback`)으로 결과를 보내 선호 실측을 갱신하게 합니다. 추천 서비스가 응답하지 않아도 설문 작성은 그대로 성공하고, 보내지 못한 설문은 5분마다(`fitzza.size-feedback.retry-delay-ms`, 기본 300000) 다시 보냅니다. `RECOMMENDATION_SERVICE_URL`이나 `REVIEW_SERVICE_TOKEN`이 비어 있으면 보내지 않으며, 그동안 쓴 설문은 두 값을 설정한 뒤 재시도에서 보내집니다.

product-service(8082), order-service(8083), community-service(8084), review-service(8085)는 호스트에 공개하지 않습니다. 이 서비스들은 `X-User-Id` 헤더를 로그인 사용자로 믿기 때문에, 포트가 열려 있으면 Gateway를 거치지 않고 헤더만 넣어 다른 사용자의 찜 여부를 보거나 장바구니를 바꾸거나 글을 쓰거나 지울 수 있습니다. 상품은 `http://localhost:8080/api/products`, 장바구니는 `http://localhost:8080/api/carts`, 커뮤니티는 `http://localhost:8080/api/community/...`처럼 Gateway로 호출합니다. FE는 `/api/v1/**`로 호출하고, Swagger·기존 도구는 `/api/**`를 그대로 씁니다. Gateway는 Java 서비스로 넘기기 전에 `/api/v1`을 `/api`로 바꿉니다. 가상 피팅·추천은 서비스가 이미 `/api/v1`을 쓰므로 바꾸지 않습니다.

notification-service의 8086 포트는 호스트에 공개하지 않습니다. 서비스 간 호출은 Compose 네트워크의 `http://notification-service:8086`을 사용하고, 공개 알림 API는 `http://localhost:8080/api/notifications`로 Gateway를 통해 호출합니다. `X-User-Id`는 Gateway에서 검증한 사용자 ID만 신뢰합니다.

Gateway는 모든 전달 요청에서 클라이언트의 `X-User-Id`를 제거하고, 보호된 사용자 API에서는 서명·만료 시각·사용자 ID(subject)를 검증한 JWT의 ID로 설정합니다.

### 사용자 역할 (USER / ADMIN)

user-service는 사용자마다 역할(`users.role`, `USER`·`ADMIN`, 기본 `USER`)을 저장합니다(이슈 #225). Access Token의 `role` 클레임에 역할이 실리고, Gateway는 검증한 토큰의 역할을 `X-User-Role` 헤더로 넘깁니다. 클라이언트가 보낸 `X-User-Role`은 `X-User-Id`와 마찬가지로 항상 지웁니다. `role` 클레임이 없는 예전 토큰이나 모르는 값은 `USER`로 넘깁니다. 관리자 API는 `X-User-Role: ADMIN`인지 확인합니다.

로그인 응답과 `GET /api/users/me` 응답에도 `role`이 있습니다. FE는 이 값으로 관리자 메뉴를 보여줄지만 정하고, 실제 권한 검사는 서버가 헤더로 합니다.

관리자 지정 API는 없습니다. 관리자 계정은 운영 DB에서 `user_service_app` 계정으로 지정하고, 지정한 사용자는 다시 로그인(또는 토큰 재발급)해야 새 역할이 토큰에 실립니다.

```sql
UPDATE user_service.users SET role = 'ADMIN' WHERE email = '<관리자 이메일>';
```

Gateway는 요청마다 `X-Request-Id`를 정해 뒤쪽 서비스로 넘기고 응답 헤더에도 담습니다(브라우저에서도 읽을 수 있음). 클라이언트가 영문·숫자·`._-` 8~64자로 보내면 그 값을 이어 쓰고, 아니면 새로 만듭니다. user·community·notification-service는 이 값을 로그 줄마다 `[요청 ID]`로 찍고, community-service는 다른 서비스를 호출할 때도 같은 값을 넘깁니다. 오류 문의를 받으면 응답의 `X-Request-Id`로 `docker compose logs | grep <ID>` 해서 같은 요청의 로그를 모아 볼 수 있습니다.

`POST /api/auth/signup`, `/api/auth/signin`, `/api/auth/refresh`, `/api/auth/signout`(또는 같은 경로의 `/api/v1/auth/...`)은 토큰 없이 호출할 수 있습니다. 회원가입에서 이메일이나 닉네임이 이미 쓰이고 있으면 409 `DUPLICATE_VALUE`와 함께 `errors` 배열에 중복된 필드를 모두 담아 돌려줍니다. 그 외 사용자 API(`GET /api/users/me`, `PATCH /api/users/me`)에는 `Authorization: Bearer <access-token>`이 필요합니다. 추천 API(`/api/v1/recommendations/**`)도 회원만 쓸 수 있어 토큰이 없으면 Gateway가 401 `UNAUTHENTICATED`로 막습니다. 인증 실패 시 Gateway는 401을 반환합니다.

```bash
curl -H "Authorization: Bearer <access-token>" http://localhost:8080/api/users/me
curl -H "Authorization: Bearer <access-token>" http://localhost:8080/api/v1/users/me
```

API 문서(Swagger UI)는 Gateway 한 곳에서 봅니다: <http://localhost:8080/swagger-ui.html>. 오른쪽 위 목록에서 user-service, product-service, order-service, community-service, notification-service, review-service를 고르고, 로그인이 필요한 API는 `Authorize`에 Access Token을 넣은 뒤 호출합니다. 문서에서 `/api`로 시작하지 않는 API는 서비스끼리만 호출하므로 이 화면에서는 호출되지 않습니다. 운영 Gateway는 `SPRING_PROFILES_ACTIVE=prod`로 실행합니다. 이 프로파일에서는 서비스 문서 프록시 라우트(`/api-docs/**`), Gateway API 문서와 Swagger UI가 비활성화됩니다. 각 서비스의 직접 접근 문서도 끄려면 해당 서비스에 `SPRINGDOC_API_DOCS_ENABLED=false`, `SPRINGDOC_SWAGGER_UI_ENABLED=false`를 설정합니다. Compose의 `.env`만으로 프로파일이 전달되지는 않으므로 배포 설정에서 Gateway 컨테이너의 환경 변수로 지정해야 합니다.

```powershell
.\scripts\health-check.ps1
```

- 애플리케이션 상태는 서비스 컨테이너에 직접 `GET /health`로 확인합니다. 정상일 때는 `200`과 `{"status":"UP","liveness":"UP","readiness":"UP"}`을, 준비되지 않았을 때는 `503`과 `{"status":"NOT_READY","liveness":"UP","readiness":"DOWN"}`을 반환합니다. Gateway는 다른 서비스의 `/health`를 프록시하지 않습니다.
- 로컬에서 직접 확인 가능한 상태 주소: Config <http://localhost:8888/health>, Discovery <http://localhost:8761/health>, Gateway <http://localhost:8080/health>, Virtual Try-On <http://localhost:8091/health>, Recommendation <http://localhost:8092/health>
- Eureka 대시보드: <http://localhost:8761>
- LocalStack 상태: <http://localhost:4566/_localstack/health>
- Jaeger UI(분산 추적): <http://localhost:16686> — Compose는 샘플링 `1.0`과 OTLP `http://jaeger:4318/v1/traces`를 넣습니다. yml 기본 샘플링은 `0.0`(꺼짐)이라 운영에 그대로 올려도 전송하지 않습니다. 운영에서 켤 때는 `MANAGEMENT_TRACING_SAMPLING_PROBABILITY`와 `MANAGEMENT_OTLP_TRACING_ENDPOINT`를 함께 설정합니다. config-service·discovery-service는 추적 대상에서 제외합니다.

Gateway를 통한 예시 호출:

```bash
curl http://localhost:8080/api-docs/user-service
curl http://localhost:8080/api/products
curl http://localhost:8080/api/v1/products
curl -X POST http://localhost:8080/api/v1/recommendations \
  -H 'Authorization: Bearer <access-token>' \
  -H 'Content-Type: application/json' \
  -d '{"user_id":"00000000-0000-0000-0000-000000000001","limit":10}'
```

## 서비스별 DB 계정

운영의 Java 6개 서비스(user·product·order·community·review·notification)는 서비스 전용 DB 계정(`<스키마>_app`, 예: `user_service_app`)으로 접속합니다.
각 계정은 자기 스키마의 소유자라서 그 안에서만 Flyway로 테이블을 만들고 바꿀 수 있고, 다른 서비스 스키마에는 접근할 수 없습니다.

- 앱 설정: `USER_SERVICE_DB_USER`/`USER_SERVICE_DB_PASSWORD`처럼 서비스별 값을 필수로 사용합니다. Java 6개 서비스에는 공용 `POSTGRES_USER`/`POSTGRES_PASSWORD` fallback이 없습니다.
- Kubernetes: `fitzza-db-secrets`에 6개 서비스의 `*_DB_USER`/`*_DB_PASSWORD` 12개 키를 등록합니다. 공개 가능한 형식은 `infra/k8s/base/db-secret.example.yaml`을 참고합니다.
- 계정 준비: 관리자 계정(로컬 `POSTGRES_USER`, RDS 마스터 계정)으로 `infra/postgres/service-accounts.sql`을 실행합니다. 비밀번호는 `USER_SERVICE_DB_PASSWORD` 같은 환경 변수로만 받고, 값이 없는 서비스는 건너뜁니다. 계정 생성, 스키마 소유자 지정, 관리자 계정이 만든 기존 테이블의 소유자 이전을 한 번에 하며 다시 실행해도 됩니다. psql 15 이상이 필요합니다.

```bash
psql -v ON_ERROR_STOP=1 -U <관리자> -d fitzza -f infra/postgres/service-accounts.sql
```

## DB 스키마 (Flyway)

현재 **product-service**, **order-service**는 `src/main/resources/db/migration`의 Flyway 스크립트로 테이블을 관리하고, Hibernate `ddl-auto`는 `validate`입니다. 나머지 JPA 서비스는 아직 `ddl-auto: update`이며, 같은 규칙으로 서비스 담당자가 Flyway를 붙입니다. `infra/postgres/init.sql`은 서비스별 PostgreSQL 스키마만 만듭니다.

공통 규칙:

1. **버전 네이밍:** `V1__`, `V2__` … 단순 순번. 동시에 작업할 때는 슬랙에 번호를 미리 공유한다.
2. **baseline-on-migrate:** 이미 테이블이 있는 로컬/RDS는 현재 상태를 baseline(V1)으로 기록하고 V1 SQL은 다시 실행하지 않는다. 빈 스키마(신규 볼륨·RDS)에서는 V1이 테이블을 생성한다.
3. **스크립트 불변:** 한 번 머지·실행된 SQL은 직접 수정하지 않고, 변경은 새 버전 파일(`V…sql`)을 추가한다.

## 기존 사용자 DB 업그레이드

기존 DB를 재사용하면 `user_service.users`의 email과 nickname 유니크 제약 이름을 각각 `uk_users_email`, `uk_users_nickname`으로 변경한 뒤 시작합니다. 이전 자동 생성 이름의 제약이 남으면 동시 가입 시 중복 계정 오류로 분류되지 않을 수 있습니다. 신규 DB에는 엔티티 매핑에 명시한 이름으로 제약을 생성합니다(user-service가 Flyway로 전환되면 마이그레이션 기준으로 바뀝니다).

성별 코드가 `W`/`M`에서 `F`/`M`으로 바뀌었습니다. 예전 DB에는 `gender`에 `W`/`M`만 허용하는 검사 제약이 남아 있어 `F`를 저장하지 못하므로, 기존 DB를 재사용하면 아래를 한 번 실행합니다. 체형(`body_type`) 컬럼은 더 이상 쓰지 않으며 남아 있어도 동작에는 영향이 없습니다.

```sql
ALTER TABLE user_service.user_body DROP CONSTRAINT IF EXISTS user_body_gender_check;
UPDATE user_service.user_body SET gender = 'F' WHERE gender = 'W';
```

## 로컬 빌드

Java 21이 필요합니다. 별도 Gradle 설치 없이 Wrapper를 사용합니다.

product-service를 직접 실행할 때는 DB 비밀번호에 맞는 `POSTGRES_PASSWORD` 환경 변수를 설정해야 합니다. 애플리케이션에는 기본 비밀번호가 없으며, `.env` 파일은 직접 실행 시 자동으로 로드되지 않습니다.

```bash
./gradlew test
```

FastAPI 서비스는 각 디렉터리의 `requirements.txt`로 별도 설치할 수 있습니다.

## 디렉터리

```text
config-service/          Spring Cloud Config (native repository)
discovery-service/       Netflix Eureka
gateway-service/         Spring Cloud Gateway
user-service/            사용자 도메인
product-service/         상품 도메인
order-service/           주문 도메인
community-service/       커뮤니티 도메인
review-service/          리뷰 도메인
notification-service/    알림 도메인
vton-service/            FastAPI 가상 피팅 작업 API
recommendation-service/  FastAPI 추천 API
infra/                   PostgreSQL 초기화
scripts/                 운영 보조 스크립트
performance/             k6 시나리오(구매 여정 스모크 등). 본격 부하는 인프라 합의 후
```

구매 API 스모크는 [performance/README.md](performance/README.md)의 `purchase_flow.js`를 따른다. 기본은 VU 1회이며 운영 ALB에 큰 부하는 올리지 않는다.

크롤러에서 Jev 색상 정규화로 전달하는 데이터 계약은 [infra/data-pipeline/README.md](infra/data-pipeline/README.md)를 따릅니다.

AWS 배포 기반은 [infra/aws/cloudformation/README.md](infra/aws/cloudformation/README.md)를 따릅니다. CloudFormation은 전용 VPC, 단일 NAT Gateway, EKS, S3, ECR을 구성하며 Managed Node Group은 비용 보호를 위해 `desired=0`으로 시작합니다.

## 구현 원칙

- 서비스별 데이터 소유권을 전제로 PostgreSQL 스키마를 분리했습니다. product·order는 Flyway로 DDL을 관리하고, 다른 JPA 서비스도 동일 정책으로 전환합니다.
- 비동기 연동의 개발 환경은 LocalStack의 SQS/S3로 대체합니다.
- 운영 비밀값은 저장소에 커밋하지 않고 환경 변수로 주입합니다.
- 인증은 Gateway의 Access Token 검증, Redis에 저장하는 Refresh Token, 로그아웃 시 Access Token 블랙리스트로 구현되어 있습니다. 서비스 간 호출은 서비스별 토큰(`X-Service-Token`)으로 인증하며, 관측성 대시보드는 아직 구성하지 않았습니다.

## Refresh Token 쿠키 인증

로그인(`POST /api/auth/signin`)은 `{ "accessToken": "...", "userId": 1, "nickname": "...", "role": "USER" }`을 반환합니다.
Refresh Token은 `Set-Cookie: refreshToken=...; Path=/api; HttpOnly; SameSite=Lax`로만 전달합니다.
Refresh Token을 JSON 응답에 포함하거나 JSON 요청 본문에서 받지 않습니다.

재발급(`POST /api/auth/refresh`)은 쿠키를 포함하고 요청 본문 없이 호출합니다. 응답에는
`{ "accessToken": "..." }`만 포함되며, 쿠키는 새 Refresh Token으로 교체됩니다. 이전 토큰은 다시 사용할 수 없습니다.
로그아웃(`POST /api/auth/signout`)도 쿠키를 포함하고 요청 본문 없이 호출하면 토큰을 폐기하고 브라우저 쿠키를 삭제합니다.
`Authorization: Bearer <access-token>`을 함께 보내면 Access Token도 폐기합니다.
쿠키가 없거나 비어 있으면 400 `INVALID_REQUEST`, 유효하지 않은 Refresh Token이면 401 `INVALID_REFRESH_TOKEN`을 반환합니다.
Gateway의 `/api/v1/auth/...` 경로에서도 동일하게 동작합니다.

브라우저에서 로그인·재발급·로그아웃을 호출할 때는 `fetch(url, { method: 'POST', credentials: 'include' })` 또는
Axios의 `withCredentials: true`를 설정해야 합니다. Gateway는 `CORS_ALLOWED_ORIGINS`에 명시한 주소에만
쿠키를 포함한 요청을 허용하므로 `*`를 사용하지 않습니다. `SameSite=Lax`를 사용하므로 FE와 API는 같은 사이트에 있어야 합니다.
다른 API를 호출할 때는 기존처럼 Bearer 헤더로 Access Token을 전달합니다.

쿠키 유효기간은 `JWT_REFRESH_EXPIRATION_SECONDS`(기본 30일)를 따르며 Redis의 토큰 만료 시간과 같습니다.
쿠키는 발급한 호스트에만 전송되며, 경로가 `/api`이므로 두 API 접두사에서 모두 동작합니다.
`REFRESH_COOKIE_SECURE`로 Secure 속성을 설정하며, 미지정 시 기본값은 false입니다.
Compose는 `.env` 또는 실행 환경의 값을 user-service에 전달하며, 로컬 HTTP 개발에서는 false를 사용합니다.
운영 HTTPS 배포에서는 `REFRESH_COOKIE_SECURE=true`를 지정해야 합니다. 로컬에서 직접 실행할 때도
user-service 환경 변수 또는 `.env`로 설정합니다.
