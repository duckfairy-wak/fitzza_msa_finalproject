# 백엔드 API k6 성능 테스트

JavaScript는 Node.js가 아닌 k6로 실행한다. k6 1.3.0 기준이며 별도 npm 패키지는 필요하지 않다.

| 스크립트 | 용도 |
| --- | --- |
| `api.js` | 조회 부하 (`PROFILE=public\|member\|all`) |
| `purchase_flow.js` (FITZZA-296) | 회원가입 → 로그인 → 상품 → 장바구니 → **주문 생성** (쓰기 포함 스모크) |

## 조회 부하 (`api.js`)

| PROFILE | API |
| --- | --- |
| public (기본) | 상품 목록, 카테고리, 커뮤니티 목록 |
| member | 내 프로필, 장바구니, 주문 목록, 알림 목록 |
| all | 위 API 전체 |

각 VU는 선택한 API를 순차 요청하고 요청마다 1초 대기한다. 모든 API에 동일한 비중으로
요청하므로 실제 사용자 행동 비율과는 다르다. 회원 테스트는 하나의 계정을 공유하며
다수 사용자의 데이터 분포를 재현하지 않는다. 빈 목록도 정상 응답으로 인정한다.
GET 조회만 포함하며 조회수를 변경하는 게시글 상세, 주문 생성, AI 작업은 포함하지 않는다.

## PowerShell 실행

### Docker Compose로 실행

k6를 로컬에 설치하지 않고 저장소 루트에서 실행할 수 있다. 먼저 `.env.example`을 참고해
Compose 필수 환경 변수를 설정하고 백엔드를 실행해 API가 준비된 것을 확인한다.

```powershell
docker compose up --build -d
docker compose run --rm k6
```

k6는 `performance` 프로필에 있으며 서비스 이름을 지정해 실행할 때 활성화된다.
일반 `docker compose up`에서는 실행되지 않는다. k6에 의존 서비스를 연결하지 않았으므로
`run k6`만으로 백엔드가 시작되지는 않는다. 기본 대상은 Compose 내부의
`http://gateway-service:8080`이고 컨테이너의 `localhost`는 호스트가 아니다.

Compose는 `.env`의 `K6_BASE_URL`, `K6_PROFILE`, `K6_VUS`, `K6_DURATION_SECONDS`,
`K6_P95_MS`, `K6_ACCESS_TOKEN`을 k6 환경 변수로 변환해 전달한다.
회원 테스트는 `K6_PROFILE=member` 또는 `all`과 유효한 `K6_ACCESS_TOKEN`을 설정한다.
실행 단위로는 컨테이너 환경 변수를 덮어쓸 수도 있다.

```powershell
docker compose run --rm -e VUS=1 -e DURATION_SECONDS=10 k6
# EKS Gateway를 대상으로 실행할 때는 실제 외부 API origin으로 바꾼다.
docker compose run --rm -e BASE_URL=https://api.example.com k6
```

결과는 호스트의 `performance/results/summary.json`, `performance/results/report.html`에
저장되며 다음 실행 시 덮어쓴다. 결과 디렉터리는 Git에서 제외된다. 스크립트는 읽기 전용으로
마운트하고 결과 디렉터리는 Linux의 bind mount 권한 차이를 피하기 위해 컨테이너 root로 쓴다.
호스트 Linux에서 결과 파일은 root 소유가 될 수 있다.
HTML 보고서는 테스트 종료 후 브라우저로 연다. 결과를 출력한 뒤 k6 컨테이너는 종료한다.

### 로컬 k6로 실행

먼저 k6를 설치하고 저장소 루트에서 실행한다. 환경 변수의 URL을 실제 테스트 대상으로 바꾼다.

```powershell
$env:BASE_URL = 'http://localhost:8080'
$env:PROFILE = 'public'
$env:VUS = '5'
$env:DURATION_SECONDS = '60'
$env:P95_MS = '1000'
k6 run performance/api.js
```

회원 API는 테스트 계정의 유효한 JWT access token을 외부 환경 변수 `ACCESS_TOKEN`에 넣고
`PROFILE=member` 또는 `all`로 실행한다. `Bearer ` 접두사는 코드가 붙인다.
`X-User-Id` 헤더를 직접 주입하지 않는다. 토큰 만료 시 실패로 기록되므로 테스트 종료까지
유효한 토큰을 사용한다. 스크립트는 로그인이나 토큰 갱신 시간을 측정하지 않는다.

## 설정과 결과

- `BASE_URL`: 필수, 경로 없는 Gateway origin. 예: `https://api.example.com`.
- `VUS`: 기본 5, 최대 50. 동시 사용자 수이며 RPS가 아니다.
- `DURATION_SECONDS`: 기본 60, 1~600초 부하 유지. 앞뒤 각각 10초 ramp와 최대 15초 종료 대기 추가.
- `P95_MS`: 기본 1000, 1~30000ms. API마다 p95가 이 값 미만이어야 한다.

사전 요청으로 HTTP 200과 JSON 구조를 확인한 뒤 부하를 시작한다. API별 오류율 1% 미만,
응답 검증 성공률 99% 초과, 최소 요청 1개를 요구한다. HTTP 오류율 기준 위반은 10초 이후
조기 중단하며 응답시간·검증 실패 기준은 종료 시 판정한다. 사전 요청은 성능 기준에서 제외한다.
초기 p95 값은 임시 비교 기준이며 서비스 SLO에 맞춰 조정한다.

종료 시 콘솔에 API별 기준 판정을 출력하고 현재 디렉터리에 `summary.json`을 쓴다.
기준 미달이면 종료 코드가 0이 아니므로 GitHub Actions에서도 `k6 run performance/api.js`를
그대로 실행하면 실패를 감지한다. Actions에서 토큰은 GitHub Secret을 `ACCESS_TOKEN` 환경
변수로 전달하고, `summary.json`은 `if: always()` artifact 단계로 업로드한다.

HTML 시간별 보고서를 추가하려면 실행 전에 아래 환경 변수도 설정한다.

```powershell
$env:K6_WEB_DASHBOARD = 'true'
$env:K6_WEB_DASHBOARD_PORT = '-1'
$env:K6_WEB_DASHBOARD_EXPORT = 'k6-report.html'
k6 run performance/api.js
```

로컬 k6는 루트 `.env`를 자동으로 읽지 않는다(Compose는 위 `K6_*` 설정을 전달한다).
응답 본문·토큰은 출력하지 않는다.
실제 EKS에서 실행할 때는 노드 Ready와 운영 시간을 확인하고 VU 1부터 시작한다.
DB 연결 수·CPU·메모리·오류율을 함께 관찰하고, Jaeger 샘플링과 배포 이미지 버전을
기록해 같은 조건으로 비교한다. 외부에서 실행한 응답시간에는 네트워크와 ALB 지연도 포함된다.

## 구매 여정 (`purchase_flow.js`)

쓰기 API(장바구니 추가·주문 생성)를 포함한 end-to-end 스모크다. 기본은 VU 1 / 1회.
매 iteration마다 새 회원을 가입시키므로 운영에 큰 VU로 돌리지 않는다.

```bash
k6 run -e BASE_URL=http://localhost:8080 -e VUS=1 -e ITERATIONS=1 performance/purchase_flow.js
k6 run -e BASE_URL=https://api.fitzza.site -e VUS=1 -e ITERATIONS=1 performance/purchase_flow.js

# Compose k6 컨테이너(기본은 api.js). 구매 시나리오는 entrypoint 오버라이드:
docker compose run --rm --entrypoint k6 k6 run \
  -e BASE_URL=http://gateway-service:8080 -e VUS=1 -e ITERATIONS=1 \
  /scripts/purchase_flow.js
```

| 환경 변수 | 기본 | 설명 |
| --- | --- | --- |
| `BASE_URL` | `http://localhost:8080` | Gateway origin |
| `API_PREFIX` | `/api/v1` | FE 경로. Swagger면 `/api` |
| `VUS` / `ITERATIONS` | `1` / `1` | 스모크 |
| `PRODUCT_ID` | (목록 첫 상품) | 고정 상품 |
| `FETCH_IMAGE` | `false` | Presigned 이미지 GET |
