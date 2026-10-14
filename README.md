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
# .env의 JWT_SECRET과 INTERNAL_CALL_TOKEN에 서로 다른 32바이트 이상의 무작위 비밀값을 입력한 뒤 실행합니다.
docker compose up --build -d
```

Windows PowerShell에서는 `Copy-Item .env.example .env`를 사용합니다.

`JWT_SECRET`은 user-service가 Access Token을 서명하고 gateway-service가 검증하는 데 함께 쓰는 32바이트 이상 문자열입니다. 로컬과 배포 환경 모두 `.env` 또는 환경 변수로 직접 설정해야 합니다. 값이 없거나 비어 있으면 Docker Compose가 시작되지 않습니다. `.env.example`에는 비밀값을 제공하지 않습니다.

`INTERNAL_CALL_TOKEN`은 신뢰하는 서비스가 내부 API를 호출할 때 `X-Internal-Token` 헤더로 보내는 비밀값입니다. user-service(`/internal/users`), notification-service(`/internal/notifications/events`), product-service의 내부 API가 같은 값을 검사합니다. community-service는 user-service 내부 API를 호출하고, order-service는 product-service `/internal/product-options`를 호출합니다. 값이 없거나 비어 있으면 해당 서비스가 시작되지 않으며, 헤더가 없거나 일치하지 않으면 HTTP 401 `UNAUTHENTICATED`를 반환합니다. Gateway는 클라이언트가 보낸 `X-Internal-Token`을 전달하기 전에 제거합니다. user-service의 8081 포트와 notification-service의 8086 포트는 호스트에 공개하지 않습니다.

브라우저에서 Gateway를 호출할 FE 주소는 `CORS_ALLOWED_ORIGINS`(쉼표로 구분, 기본 `http://localhost:3000,http://localhost:5173`)로 정합니다. 목록에 없는 주소에서 온 브라우저 요청은 403으로 거부됩니다. 토큰은 `Authorization` 헤더로 보내므로 쿠키 허용은 켜지 않았습니다.

토큰 유효기간은 `JWT_EXPIRATION_SECONDS`(Access Token, 1~900초, 기본 15분)와 `JWT_REFRESH_EXPIRATION_SECONDS`(Refresh Token, 기본 30일)로 바꿀 수 있습니다. Refresh Token은 Redis에 저장합니다.

로그아웃(`POST /api/auth/signout`)은 Body의 Refresh Token을 Redis에서 지웁니다. `Authorization: Bearer <access-token>` 헤더를 함께 보내면 그 Access Token도 남은 만료 시간 동안 Redis 블랙리스트에 올라가고, Gateway는 블랙리스트에 있는 토큰을 401 `INVALID_TOKEN`으로 거부합니다. Gateway가 Redis를 조회하지 못하면 토큰이 실린 요청은 503 `AUTH_UNAVAILABLE`로 응답합니다.

알림 API(`GET /api/notifications`, `GET /api/notifications/unread-count`, `PATCH /api/notifications/{notificationId}/read`)는 로그인한 사용자의 알림만 다룹니다. 알림은 다른 서비스가 `POST /internal/notifications/events`로 보낸 이벤트로 만들어지며, 같은 `eventId`로 다시 보내도 한 번만 저장됩니다. 다른 사람이 내 게시글에 댓글이나 답글을 달면 community-service가 댓글 저장이 확정된 뒤 별도 스레드에서 알림을 보냅니다. 알림 서비스가 꺼져 있으면 경고 로그만 남기고 댓글 작성은 그대로 성공합니다. 투표는 community-service가 1분마다(`fitzza.vote.close-check-delay-ms`, 기본 60000) 마감 시각이 지난 글을 찾아 마감 처리하고, 작성자에게 `VOTE_CLOSED` 알림을 보냅니다. 알림 서비스가 꺼져 있어 보내지 못한 알림은 다음 실행에서 성공할 때까지 다시 보냅니다. 실패한 글은 재시도 순서가 뒤로 밀려 새로 마감된 투표의 알림을 막지 않습니다. 작성자가 직접 조기 종료한 투표에는 알림을 보내지 않습니다.

order-service(8083), community-service(8084), review-service(8085)도 호스트에 공개하지 않습니다. 이 서비스들은 `X-User-Id` 헤더를 로그인 사용자로 믿기 때문에, 포트가 열려 있으면 Gateway를 거치지 않고 헤더만 넣어 다른 사용자의 장바구니를 바꾸거나 글을 쓰거나 지울 수 있습니다. 장바구니는 `http://localhost:8080/api/carts`, 커뮤니티는 `http://localhost:8080/api/community/...`처럼 Gateway로 호출합니다.

notification-service의 8086 포트는 호스트에 공개하지 않습니다. 내부 호출은 Compose 네트워크의 `http://notification-service:8086`을 사용하고, 공개 알림 API는 `http://localhost:8080/api/notifications`로 Gateway를 통해 호출합니다. `X-User-Id`는 Gateway에서 검증한 사용자 ID만 신뢰합니다.

Gateway는 모든 전달 요청에서 클라이언트의 `X-User-Id`를 제거하고, 보호된 사용자 API에서는 서명·만료 시각·사용자 ID(subject)를 검증한 JWT의 ID로 설정합니다.

`POST /api/auth/signup`, `/api/auth/signin`, `/api/auth/refresh`, `/api/auth/signout`과 `GET /api/users/profile/options`는 토큰 없이 호출할 수 있습니다. 그 외 사용자 API에는 `Authorization: Bearer <access-token>`이 필요합니다. 인증 실패 시 Gateway는 401을 반환합니다.

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
curl http://localhost:8080/api/users/profile/options
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

## 크롤링 색상 후보 → Fashion-CLIP 입력 검증

`scripts/fashion_clip_dataset_adapter.py`는 크롤러의 `color_products/candidates` JSON을 별도 디렉터리에 변환합니다. 추천 파이프라인 저장소는 수정하지 않습니다. Python 표준 라이브러리만 사용하며 입력·출력 경로는 명령행에서 지정합니다.

```powershell
python scripts/fashion_clip_dataset_adapter.py --source "C:\inspire\final-project\fashion-crawler-starter\data\color_products\candidates" --output ".data\fashion-clip-adapted"
python -m pytest tests/test_fashion_clip_dataset_adapter.py
```

출력 폴더는 입력과 겹치지 않는 **빈 폴더**여야 합니다. `report.json`에서 `ready_for_indexing`, 제외 사유, 원본 무신사 ID와 색상별 숫자 ID의 대응을 확인합니다. 적재용 JSON은 `data/<카테고리>/*.json`에 생성됩니다. 검증된 색상별 썸네일(`thumbnail_status=verified`, 유효한 `thumbnail_url`)과 색상·사이즈에 정확히 매칭된 양수 실측(`measurement_status=label_match`, 단위 cm)이 있는 상품만 내보냅니다. 미확인 사이즈 옵션은 내보내지 않습니다. 숫자 ID는 색상 후보 UUID에서 결정적으로 생성되며 원본 무신사 ID와 다릅니다.

기존 `color_products/candidates` 폴더의 색상 후보는 썸네일이 모두 미검증이므로 이 어댑터의 변환 결과가 0건인 것이 정상입니다. 이때 **추천 파이프라인의 `index_to_qdrant.py`를 실행하지 마세요.** 해당 스크립트는 입력 검증보다 먼저 기존 Qdrant 컬렉션을 삭제·재생성합니다. 이 어댑터는 이미지 URL이 실제로 열리는지 확인하지 않으며, 기존 인덱서가 색상 필드를 빈 배열로 저장하므로 색상 하드 필터링도 활성화하지 못합니다. 아래의 실제 이미지 검증 결과는 별도의 데이터셋이며, 인덱서가 신규 필드를 읽도록 변경되어야 합니다.

### 상품 단위 색상 × 실측 사이즈 초안

원본 500개 ZIP을 유지하면서 모든 상품에 `variants`와 실측 참조 관계를 추가한 **검토용** JSON을 만들 수 있습니다. 재고·판매 가능 여부는 사용하지 않습니다. 색상이 옵션에서 발견되면 `structured_option`, 상품명에서만 발견되면 `title_keyword_review`, 찾지 못하면 `unresolved`로 표시합니다. 색상별 이미지는 검증되지 않았으므로 빈 배열을 유지하고 상품 대표 이미지 URL은 원본 그대로 둡니다. 이 결과는 현재 Fashion-CLIP 인덱서 형식과 다르며 곧바로 적재해서는 안 됩니다.

```powershell
python scripts/build_color_size_dataset.py --source-zip "C:\inspire\final-project\fashion-crawler-starter\data\final_products.zip" --output ".data\color-size-projection-500"
python -m pytest tests/test_build_color_size_dataset.py
```

출력에는 `data/<카테고리>/*.json` 500개, `report.json`, 공유용 `color_size_dataset.zip`이 포함됩니다. 출력 디렉터리는 새 빈 디렉터리여야 합니다. `report.json`의 색상 출처별 건수와 `unlinked_count`를 확인해 상품명 기반 후보를 검토한 뒤 데이터 계약을 확정해야 합니다.

### 500개 상품의 색상별 썸네일 실제 검증

`scripts/audit_color_thumbnail_links.py`는 원본 ZIP의 상품 500개를 대상으로 공개 상품 페이지를 조회합니다. 사이트의 `OtherColorGoods.OTHER_COLOR`에서 별도 상품 ID·색상명·사진 URL을, `Options.basic.optionValues`에서 동일 상품 ID의 색상 옵션 사진을 읽습니다. 사이트가 제공하지 않은 상품 ID나 색상명은 만들지 않습니다. 이미지 URL에는 GET 요청을 보내 파일 시그니처를 확인합니다.

```powershell
python scripts/audit_color_thumbnail_links.py --source-zip "C:\inspire\final-project\fashion-crawler-starter\data\final_products.zip" --output ".data\color-thumbnail-live-500"
python -m pytest tests/test_audit_color_thumbnail_links.py
```

`report.json`에 원본 500개 중 자기 상품 ID에 검증된 색상·사진 연결이 있는 개수, 별도 상품 ID 발견 개수, 이미지 검증 결과가 나옵니다. `verified_color_product_images.json`에는 근거 페이지 ID가 함께 기록됩니다. `enriched_data/`와 `color_image_dataset.zip`에는 원본 500개 JSON에 `color_image_mappings`, `related_color_products`, `image_mapping_audit`를 추가한 결과가 있습니다. 추가로 발견한 별도 상품 ID의 상세 정보나 실측은 수집하지 않았습니다. 색상 옵션 전체의 사진이 존재한다는 뜻으로 해석해서는 안 됩니다. 조회 오류와 접속 제한은 `report.json`에서 확인하고, 재실행하면 성공한 페이지 결과를 재사용합니다.

### 색상 사진 근거가 있는 상품만 선별

`scripts/collect_color_qualified_pilot.py`는 위 실제 수집 근거를 이용해 상품을 우선순위대로 선별합니다. 결과는 카테고리별 20개씩 최대 100개입니다. 요청 수량을 충족하지 못하면 부족한 채로 보고하며 검증되지 않은 상품으로 채우지 않습니다.

1. 색상 옵션과 별도 색상 상품이 없는 단품: 이름에 색상이 하나 있고 대표 이미지가 열리는 상품.
2. 페이지 안 색상 드롭다운: 모든 색상 옵션에 서로 다른 상품 사진 URL이 있고 파일 응답이 확인된 상품.
3. 다른 상품 URL로 연결된 색상: 무신사의 `OTHER_COLOR` 연결에서 본 상품 색상 사진과 동일 브랜드의 별도 상품 ID·사진이 확인된 상품.
4. 이름의 색상: 위 조건에 못 미치지만 이름의 색상 하나와 대표 사진이 확인된 상품. 연결할 수 없는 다른 색상 옵션은 출력하지 않습니다.

모든 우선순위에서 남성·공용 대상, 카테고리, 양수 실측값을 확인합니다. `product_id`는 무신사의 실제 상품 ID를 유지합니다. 같은 상품 안의 색상 옵션들은 같은 상품 ID를 쓰며, 별도 상품 ID는 `related_color_products`에 넣습니다. 이름 기반 색상은 이미지 내용 자체를 자동 분류한 결과가 아니므로 `evidence`에 출처를 표시합니다.

```powershell
python -m scripts.collect_color_qualified_pilot --source-zip "C:\inspire\final-project\fashion-crawler-starter\data\final_products.zip" --evidence-dir ".data\color-thumbnail-live-500" --output ".data\color-qualified-pilot-100" --per-category 20
python -m pytest tests/test_audit_color_thumbnail_links.py tests/test_collect_color_qualified_pilot.py
```

결과: `data/<카테고리>/*.json` 100개, `report.json`, `color_qualified_pilot.zip`. JSON의 기존 필드는 유지하고 `color_image_mappings`, `related_color_products`, `color_collection`만 추가합니다. 추천 파이프라인의 기존 인덱서가 이 필드를 자동으로 읽지는 않으므로 인덱서 담당자에게 이 데이터 계약을 전달해야 합니다.

### 색상 사진 검증 데이터셋 500개 확장

`scripts/expand_color_qualified_dataset.py`는 기존 검증 상품을 카테고리별 100개까지 사용하고, 부족한 카테고리는 무신사의 `OTHER_COLOR`에 연결된 실제 상품 ID를 추가 조회합니다. 추가 상품도 남성·공용 여부, 카테고리, actual-size API의 양수 실측값, 색상명과 상품 사진 URL, 이미지 파일 응답을 모두 확인합니다. 성공한 상세·실측·이미지 확인 결과는 작업 디렉터리에 저장되어 재실행할 때 재사용됩니다.

```powershell
C:\inspire\final-project\fashion-crawler-starter\.venv\Scripts\python.exe -m scripts.expand_color_qualified_dataset `
  --source-zip "C:\inspire\final-project\fashion-crawler-starter\data\final_products.zip" `
  --evidence-dir ".data\color-thumbnail-live-500" `
  --crawler-root "C:\inspire\final-project\fashion-crawler-starter" `
  --work-dir ".data\color-qualified-expansion-work" `
  --output ".data\color-qualified-dataset-500" `
  --per-category 100
```

결과: `data/<카테고리>/*.json` 500개, `report.json`, `image_checks.json`, `color_qualified_dataset_500.zip`. 목표를 채우지 못하면 `report.json`의 `complete`가 `false`가 되며 검증되지 않은 상품으로 수량을 보충하지 않습니다.

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
- 인증은 Gateway의 Access Token 검증, Redis에 저장하는 Refresh Token, 로그아웃 시 Access Token 블랙리스트로 구현되어 있습니다. 서비스 간 호출은 내부 API(`X-Internal-Token`)를 사용하며, 관측성 대시보드는 아직 구성하지 않았습니다.
