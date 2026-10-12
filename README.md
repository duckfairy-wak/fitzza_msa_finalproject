# Fitzza MSA Backend

Fitzza 패션 커머스의 최소 실행형 MSA 골격입니다. 각 서비스는 독립 배포 단위이며, 현재는 상태 확인용 API와 인프라 연결 설정까지만 제공합니다.

팀 브랜치·커밋·PR·코드 규칙은 [CONTRIBUTING.md](CONTRIBUTING.md)를 따릅니다. AI 코딩 도구는 작업 전에 [AGENTS.md](AGENTS.md)를 먼저 확인해야 합니다.

## 구성

| 영역 | 서비스 | 포트 |
| --- | --- | ---: |
| Platform | Config Server | 8888 |
| Platform | Eureka Discovery | 8761 |
| Edge | API Gateway | 8080 |
| Commerce | User / Product / Order / Community | 8081-8084 |
| Messaging | Notification | 8086 |
| AI | Virtual Try-On / Recommendation (FastAPI) | 8091-8092 |
| Infra | PostgreSQL / Redis / LocalStack(S3, SQS) | 5432 / 6379 / 4566 |

## 빠른 시작

요구 사항: Docker Desktop 및 Docker Compose

```bash
cp .env.example .env
# .env의 JWT_SECRET과 INTERNAL_CALL_TOKEN에 서로 다른 32바이트 이상의 무작위 비밀값을 입력한 뒤 실행합니다.
docker compose up --build -d
```

Windows PowerShell에서는 `Copy-Item .env.example .env`를 사용합니다.

`JWT_SECRET`은 user-service가 Access Token을 서명하고 gateway-service가 검증하는 데 함께 쓰는 32바이트 이상 문자열입니다. 로컬과 배포 환경 모두 `.env` 또는 환경 변수로 직접 설정해야 합니다. 값이 없거나 비어 있으면 Docker Compose가 시작되지 않습니다. `.env.example`에는 비밀값을 제공하지 않습니다.

`INTERNAL_CALL_TOKEN`은 신뢰하는 서비스가 내부 API를 호출할 때 `X-Internal-Token` 헤더로 보내는 비밀값입니다. user-service(`/internal/users`), notification-service(`/internal/notifications/events`), product-service의 내부 API가 같은 값을 검사합니다. community-service는 user-service 내부 API를 호출하고, order-service는 product-service `/internal/product-options`를 호출합니다. 값이 없거나 비어 있으면 해당 서비스가 시작되지 않으며, 헤더가 없거나 일치하지 않으면 HTTP 401 `UNAUTHENTICATED`를 반환합니다. Gateway는 클라이언트가 보낸 `X-Internal-Token`을 전달하기 전에 제거합니다. user-service의 8081 포트와 notification-service의 8086 포트는 호스트에 공개하지 않습니다.

브라우저에서 Gateway를 호출할 FE 주소는 `CORS_ALLOWED_ORIGINS`(쉼표로 구분, 기본 `http://localhost:3000,http://localhost:5173`)로 정합니다. 목록에 없는 주소에서 온 브라우저 요청은 403으로 거부됩니다. 토큰은 `Authorization` 헤더로 보내므로 쿠키 허용은 켜지 않았습니다.

토큰 유효기간은 `JWT_EXPIRATION_SECONDS`(Access Token, 1~900초, 기본 15분)와 `JWT_REFRESH_EXPIRATION_SECONDS`(Refresh Token, 기본 30일)로 바꿀 수 있습니다. Refresh Token은 Redis에 저장합니다.

로그아웃(`POST /api/auth/signout`)은 Body의 Refresh Token을 Redis에서 지웁니다. `Authorization: Bearer <access-token>` 헤더를 함께 보내면 그 Access Token도 남은 만료 시간 동안 Redis 블랙리스트에 올라가고, Gateway는 블랙리스트에 있는 토큰을 401 `INVALID_TOKEN`으로 거부합니다. Gateway가 Redis를 조회하지 못하면 토큰이 실린 요청은 503 `AUTH_UNAVAILABLE`로 응답합니다.

알림 API(`GET /api/notifications`, `GET /api/notifications/unread-count`, `PATCH /api/notifications/{notificationId}/read`)는 로그인한 사용자의 알림만 다룹니다. 알림은 다른 서비스가 `POST /internal/notifications/events`로 보낸 이벤트로 만들어지며, 같은 `eventId`로 다시 보내도 한 번만 저장됩니다. 다른 사람이 내 게시글에 댓글이나 답글을 달면 community-service가 댓글 저장이 확정된 뒤 별도 스레드에서 알림을 보냅니다. 알림 서비스가 꺼져 있으면 경고 로그만 남기고 댓글 작성은 그대로 성공합니다.

order-service(8083), community-service(8084)도 호스트에 공개하지 않습니다. 이 서비스들은 `X-User-Id` 헤더를 로그인 사용자로 믿기 때문에, 포트가 열려 있으면 Gateway를 거치지 않고 헤더만 넣어 다른 사용자의 장바구니를 바꾸거나 글을 쓰거나 지울 수 있습니다. 장바구니는 `http://localhost:8080/api/carts`, 커뮤니티는 `http://localhost:8080/api/community/...`처럼 Gateway로 호출합니다.

notification-service의 8086 포트는 호스트에 공개하지 않습니다. 내부 호출은 Compose 네트워크의 `http://notification-service:8086`을 사용하고, 공개 알림 API는 `http://localhost:8080/api/notifications`로 Gateway를 통해 호출합니다. `X-User-Id`는 Gateway에서 검증한 사용자 ID만 신뢰합니다.

Gateway는 모든 전달 요청에서 클라이언트의 `X-User-Id`를 제거하고, 보호된 사용자 API에서는 서명·만료 시각·사용자 ID(subject)를 검증한 JWT의 ID로 설정합니다.

`POST /api/auth/signup`, `/api/auth/signin`, `/api/auth/refresh`, `/api/auth/signout`과 `GET /api/users/profile/options`, `/api/users/status`는 토큰 없이 호출할 수 있습니다. 그 외 사용자 API에는 `Authorization: Bearer <access-token>`이 필요합니다. 인증 실패 시 Gateway는 401을 반환합니다.

```bash
curl -H "Authorization: Bearer <access-token>" http://localhost:8080/api/users/me
```

API 문서(Swagger UI)는 Gateway 한 곳에서 봅니다: <http://localhost:8080/swagger-ui.html>. 오른쪽 위 목록에서 user-service, community-service, notification-service를 고르고, 로그인이 필요한 API는 `Authorize`에 Access Token을 넣은 뒤 호출합니다. 문서의 `/internal/...` API는 서비스끼리만 호출하므로 이 화면에서는 호출되지 않습니다. 운영 Gateway는 `SPRING_PROFILES_ACTIVE=prod`로 실행합니다. 이 프로파일에서는 서비스 문서 프록시 라우트(`/api-docs/**`), Gateway API 문서와 Swagger UI가 비활성화됩니다. 각 서비스의 직접 접근 문서도 끄려면 해당 서비스에 `SPRINGDOC_API_DOCS_ENABLED=false`, `SPRINGDOC_SWAGGER_UI_ENABLED=false`를 설정합니다. Compose의 `.env`만으로 프로파일이 전달되지는 않으므로 배포 설정에서 Gateway 컨테이너의 환경 변수로 지정해야 합니다.

```powershell
.\scripts\health-check.ps1
```

- Gateway 상태: <http://localhost:8080/actuator/health>
- Eureka 대시보드: <http://localhost:8761>
- LocalStack 상태: <http://localhost:4566/_localstack/health>

Gateway를 통한 예시 호출:

```bash
curl http://localhost:8080/api/users/status
curl http://localhost:8080/api/products
curl http://localhost:8080/api/v1/recommendations/status
```

## 기존 사용자 DB 업그레이드

기존 DB를 재사용하면 `user_service.users`의 email과 nickname 유니크 제약 이름을 각각 `uk_users_email`, `uk_users_nickname`으로 변경한 뒤 시작합니다. 이전 자동 생성 이름의 제약이 남으면 동시 가입 시 중복 계정 오류로 분류되지 않을 수 있습니다. 신규 DB에는 JPA가 명시한 이름으로 제약을 생성합니다.

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
notification-service/    알림 도메인
virtual-tryon-service/   FastAPI 가상 피팅 작업 API
recommendation-service/  FastAPI 추천 API
infra/                   PostgreSQL 초기화
scripts/                 운영 보조 스크립트
```

## 구현 원칙

- 서비스별 데이터 소유권을 전제로 PostgreSQL 스키마를 분리했습니다.
- 비동기 연동의 개발 환경은 LocalStack의 SQS/S3로 대체합니다.
- 운영 비밀값은 저장소에 커밋하지 않고 환경 변수로 주입합니다.
- 현재 API는 골격 검증용입니다. 인증, 도메인 모델, 이벤트 계약, 관측성 대시보드는 다음 단계에서 구체화합니다.
