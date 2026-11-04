# Fitzza MSA Backend

Fitzza 패션 커머스 백엔드 MSA입니다. 각 서비스는 독립 배포 단위이며, 클라이언트의 공개 진입점은 API Gateway입니다.

팀 브랜치·커밋·PR·코드 규칙은 [CONTRIBUTING.md](CONTRIBUTING.md)를 따릅니다. AI 코딩 도구는 작업 전에 [AGENTS.md](AGENTS.md)를 먼저 확인해야 합니다.

인증·서비스 토큰·알림·DB·메트릭 등 상세 설명은 [docs/backend.md](docs/backend.md)에 모아 두었습니다.

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

VTON API와 SQS 워커:

```bash
docker compose up --build -d vton-service vton-worker
```

기존 `.env`를 쓸 때는 `VTON_QUEUE_BACKEND=sqs`, `VTON_STORAGE_BACKEND=s3`와 LocalStack 큐 주소를 `.env.example`에 맞춥니다. 워커는 HTTP 포트를 공개하지 않으며, API·워커가 이미지를 공유하려면 공통 S3가 필요합니다. `memory` 큐 모드는 API 내부에서 처리합니다.

로컬 확인:

```powershell
.\scripts\health-check.ps1
```

- Swagger: <http://localhost:8080/swagger-ui.html>
- Eureka: <http://localhost:8761>
- Jaeger: <http://localhost:16686>
- Config health: <http://localhost:8888/health>
- Gateway health: <http://localhost:8080/health>
- VTON / Recommendation health: <http://localhost:8091/health>, <http://localhost:8092/health>

IDE에서 서비스를 직접 실행할 때는 `.env`가 자동 로드되지 않습니다. `CONFIG_SERVICE_URL`(기본 `http://localhost:8888`), `DISCOVERY_SERVICE_URL`(기본 `http://localhost:8761/eureka/`)을 실행 설정에 넣습니다.

FE는 Gateway의 `/api/v1/**`로 호출합니다. Swagger·기존 도구는 `/api/**`도 사용하며, Gateway가 `/api/v1`을 Java 서비스의 `/api`로 넘깁니다. user·product·order·community·review·notification의 API 포트는 호스트에 공개하지 않으므로 Gateway로만 호출합니다.

자세한 인증·토큰·연동 규칙: [docs/backend.md](docs/backend.md)

## 로컬 빌드

Java 21이 필요합니다. 별도 Gradle 설치 없이 Wrapper를 사용합니다.

```bash
./gradlew test
```

FastAPI 서비스는 각 디렉터리의 `requirements.txt`로 별도 설치할 수 있습니다. product-service를 직접 실행할 때는 DB 비밀번호에 맞는 환경 변수가 필요합니다(애플리케이션 기본 비밀번호 없음).

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
docs/                    백엔드 상세·ERD
infra/                   PostgreSQL, data-pipeline, aws, k8s 등
scripts/                 운영 보조 스크립트
performance/             k6 시나리오(구매 여정 스모크 등). 본격 부하는 인프라 합의 후
```

크롤러·색상·벡터 파이프라인: [infra/data-pipeline/README.md](infra/data-pipeline/README.md)  
AWS 배포 기반: [infra/aws/cloudformation/README.md](infra/aws/cloudformation/README.md)  
ERD: [docs/erd/README.md](docs/erd/README.md)  
관측성: [infra/aws/observability/README.md](infra/aws/observability/README.md)

## 구현 원칙

- 서비스별 데이터 소유권을 전제로 PostgreSQL 스키마를 분리했습니다. Java 6개 서비스는 `<스키마>_app` 계정과 Flyway(`ddl-auto: validate`)를 사용합니다.
- 비동기 연동의 개발 환경은 LocalStack의 SQS/S3로 대체합니다.
- 운영 비밀값은 저장소에 커밋하지 않고 환경 변수로 주입합니다.
- 인증은 Gateway의 Access Token 검증, Redis에 저장하는 Refresh Token, 로그아웃 시 Access Token 블랙리스트입니다. 서비스 간 호출은 `X-Service-Token`으로 인증합니다.
