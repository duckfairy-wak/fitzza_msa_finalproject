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
| Infra | PostgreSQL / Redis / LocalStack(S3, SQS) | 5432 / 6379 / 4566 |

## 빠른 시작

요구 사항: Docker Desktop 및 Docker Compose

```bash
cp .env.example .env
# .env의 JWT_SECRET과 INTERNAL_CALL_TOKEN 및 아래 TLS 파일 경로를 설정한 뒤 실행합니다.
docker compose up --build -d
```

Windows PowerShell에서는 `Copy-Item .env.example .env`를 사용합니다.

`JWT_SECRET`은 user-service가 Access Token을 서명하고 gateway-service가 검증하는 데 함께 쓰는 32바이트 이상 문자열입니다. 로컬과 배포 환경 모두 `.env` 또는 환경 변수로 직접 설정해야 합니다. 값이 없거나 비어 있으면 Docker Compose가 시작되지 않습니다. `.env.example`에는 비밀값을 제공하지 않습니다.

`INTERNAL_CALL_TOKEN`은 신뢰하는 서비스가 `/internal/users` 및 `/internal/users/{userId}/body` 호출 시 `X-Internal-Token` 헤더로 보내는 별도의 비밀값입니다. user-service와 호출이 필요한 서비스에만 같은 값을 주입합니다. 지금은 작성자 닉네임을 조회하는 community-service가 호출합니다. 값이 없거나 비어 있으면 시작되지 않으며, 헤더가 없거나 일치하지 않으면 HTTP 401을 반환합니다. user-service의 8081 포트는 호스트에 공개하지 않습니다. 내부 호출은 Compose 네트워크의 `https://user-service:8081`을 사용하고 공개 API는 Gateway를 사용합니다.

### User Service TLS

로컬과 배포 환경 모두 user-service는 HTTPS로 실행하며 Eureka에는 인증서의 DNS 이름과 보안 포트만 등록합니다. community-service의 `fitzza.user-service.base-url` 기본값은 `https://user-service`이며 HTTP URL을 설정하면 시작에 실패합니다. 로드 밸런싱 후에도 HTTP 연결을 거부하고 리디렉션을 따르지 않습니다. 인증서 체인과 호스트 이름은 JVM 기본 검증을 사용합니다. HTTP 허용 또는 인증서 검증 생략 옵션은 제공하지 않습니다.

Compose 실행 전에 다음 파일을 저장소 밖에 준비하고 `.env`에 절대 경로를 지정합니다. 파일은 컨테이너의 `fitzza` 사용자가 읽을 수 있어야 합니다.

- `USER_SERVICE_TLS_CERTIFICATE_FILE`: `DNS:user-service` SAN을 포함하는 PEM 서버 인증서 및 중간 인증서 체인.
- `USER_SERVICE_TLS_PRIVATE_KEY_FILE`: 해당 인증서의 PEM 개인 키.
- `USER_SERVICE_TLS_TRUSTSTORE_FILE`: 발급 CA 인증서를 담은 JKS truststore. 개인 키는 포함하지 않습니다. community-service와 Gateway에 읽기 전용으로 마운트됩니다.

개발 환경에서는 로컬 CA로 인증서를 발급하고 아래와 같이 공개 CA 인증서를 truststore에 넣을 수 있습니다. `keytool`이 요청하는 저장소 암호는 직접 정합니다. 런타임은 공개 인증서 항목만 읽으므로 암호를 주입하지 않습니다. 운영 환경에서는 배포용 CA 인증서와 키를 사용합니다.

```bash
keytool -importcert -alias user-service-ca -file /absolute/path/ca.crt \
  -keystore /absolute/path/user-service-truststore.jks -storetype JKS
```

Compose 외부 배포에서는 `USER_SERVICE_TLS_CERTIFICATE`, `USER_SERVICE_TLS_PRIVATE_KEY`에 Spring 리소스 경로(`file:/...`)를 지정하고 `USER_SERVICE_HOSTNAME`을 인증서 SAN과 일치시킵니다. community-service와 Gateway JVM에는 `-Djavax.net.ssl.trustStore=/path/to/truststore.jks -Djavax.net.ssl.trustStoreType=JKS`를 지정합니다. user-service의 TLS 또는 Eureka 보안 포트를 끄면 닉네임 요청은 실패하며 HTTP로 전환되지 않습니다.

토큰 유효기간은 `JWT_EXPIRATION_SECONDS`(Access Token, 기본 7일)와 `JWT_REFRESH_EXPIRATION_SECONDS`(Refresh Token, 기본 30일)로 바꿀 수 있습니다. Refresh Token은 Redis에 저장합니다.

```powershell
.\scripts\health-check.ps1
```

- Gateway 상태: <http://localhost:8080/actuator/health>
- Eureka 대시보드: <http://localhost:8761>
- LocalStack 상태: <http://localhost:4566/_localstack/health>

Gateway를 통한 예시 호출:

```bash
curl http://localhost:8080/api/v1/users/status
curl http://localhost:8080/api/v1/products/status
curl http://localhost:8080/api/v1/recommendations/status
```

## 기존 사용자 DB 업그레이드

기존 DB를 재사용하면 `user_service.users`의 email과 nickname 유니크 제약 이름을 각각 `uk_users_email`, `uk_users_nickname`으로 변경한 뒤 시작합니다. 이전 자동 생성 이름의 제약이 남으면 동시 가입 시 중복 계정 오류로 분류되지 않을 수 있습니다. 신규 DB에는 JPA가 명시한 이름으로 제약을 생성합니다.

## 로컬 빌드

Java 21이 필요합니다. 별도 Gradle 설치 없이 Wrapper를 사용합니다.

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
