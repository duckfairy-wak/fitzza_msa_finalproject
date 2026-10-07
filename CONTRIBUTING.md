# Fitzza 협업 규칙

이 문서는 Fitzza 저장소의 브랜치, 커밋, Pull Request, 코드 작성 규칙을 한곳에 정리한 기준 문서입니다. 다음 Notion 문서를 2026-10-07에 저장소 환경에 맞게 옮겼습니다.

- [GitHub Rules: 브랜치 전략/커밋 규칙/PR 리뷰](https://app.notion.com/p/6a74052e01c5839b9c4381d9348cc788)
- [Code Convention: 네이밍/포맷터/린트](https://app.notion.com/p/c564052e01c582c2adfa811674e4ad2d)

Notion 규칙이 변경되면 이 문서와 AI 도구용 지침 파일도 같은 PR에서 갱신합니다.

## 1. 브랜치 전략

```text
main
└── develop
    ├── feature/<기능명>
    ├── fix/<오류명>
    ├── docs/<문서명>
    ├── style/<대상명>
    ├── refactor/<대상명>
    └── setting/<설정명>
```

- `main`: 최종 제출 또는 배포 가능한 안정 버전입니다.
- `develop`: 기능 개발이 모이는 통합 브랜치입니다.
- 작업 브랜치: 하나의 작업 목적만 다루며 `develop`에서 생성합니다.
- `main`과 `develop`에 직접 커밋하거나 직접 push하지 않습니다.
- 작업 브랜치는 Pull Request를 통해 `develop`에 병합합니다.
- 초기 저장소에서 `develop`을 처음 생성하는 push만 부트스트랩 예외로 허용합니다.

### 브랜치 이름

형식은 `<작업유형>/<기능명>`이며 영문 소문자와 kebab-case를 사용합니다.

| 유형 | 용도 | 예시 |
| --- | --- | --- |
| `feature` | 새로운 기능 | `feature/order-create` |
| `fix` | 오류 수정 | `fix/login-error` |
| `docs` | 문서 변경 | `docs/api-guide` |
| `style` | UI/CSS 또는 코드 포맷 | `style/admin-page` |
| `refactor` | 동작 변화 없는 구조 개선 | `refactor/order-service` |
| `setting` | 빌드·환경·CI 설정 | `setting/msa-scaffold` |

### 작업 시작

```bash
git switch develop
git pull origin develop
git switch -c feature/order-create
```

## 2. 커밋 규칙

한 커밋에는 하나의 작업 목적만 포함합니다.

```text
[작업유형]_날짜/파일명 또는 기능명

- 작업한 내용
- 변경한 이유
- 확인한 내용
```

- 날짜는 커밋하는 날의 일자 두 자리(`DD`)를 사용합니다.
- 대상이 여러 파일이면 파일 목록 대신 기능명을 사용합니다.
- 제목은 간결하게 쓰고 본문에는 작업, 이유, 검증 결과를 기록합니다.

| 유형 | 용도 |
| --- | --- |
| `[Add]` | 기능·파일·화면 추가 |
| `[Fix]` | 오류 수정 |
| `[Update]` | 기존 기능 또는 내용 개선 |
| `[Remove]` | 불필요한 코드·파일 제거 |
| `[Refactor]` | 동작 변화 없는 구조 개선 |
| `[Docs]` | 문서 변경 |
| `[Style]` | 디자인·CSS·포맷 변경 |
| `[Setting]` | 환경·빌드·CI 설정 |

예시:

```text
[Add]_07/Order_Create

- 주문 생성 API와 요청 DTO 추가
- 상품 주문 흐름을 제공하기 위해 구현
- order-service Gradle 테스트 통과 확인
```

## 3. Pull Request 규칙

- 기본 방향은 `작업 브랜치 → develop`입니다.
- PR 제목은 `[작업유형] 작업 요약` 형식을 사용합니다.
- 작업 내용, 변경 이유, 확인한 내용, 참고 사항을 본문에 작성합니다.
- 리뷰 승인, CI 성공, 충돌 없음, 민감 정보 없음, 문서 반영을 확인한 뒤 병합합니다.
- 리뷰 의견은 문제 위치, 이유, 개선 방향을 구체적으로 작성합니다.
- 충돌은 관련 파일을 수정한 팀원과 함께 확인하며 임의로 코드를 삭제하지 않습니다.

PR 템플릿은 [.github/PULL_REQUEST_TEMPLATE.md](.github/PULL_REQUEST_TEMPLATE.md)에 있습니다.

## 4. 공통 코드 원칙

- 이름만 보고 역할을 이해할 수 있게 작성합니다.
- 함수와 메서드는 한 가지 역할만 수행합니다.
- 긴 함수는 책임 단위로 분리하고 중복 로직은 공통화합니다.
- 주석은 의도나 제약을 설명할 때만 사용하며 코드 동작을 그대로 반복하지 않습니다.
- 사용하지 않는 변수, 함수, import와 디버그 로그를 제거합니다.
- API Key, 비밀번호, 토큰, 개인정보를 커밋하지 않습니다.
- 환경값은 환경 변수로 받고 공개 가능한 예시만 `.env.example`에 작성합니다.

## 5. Java/Spring 규칙

- Java 21과 Gradle Wrapper를 사용합니다. Maven 빌드 파일을 추가하지 않습니다.
- 패키지명은 소문자 `com.fitzza.<domain>` 형식을 사용합니다.
- 클래스와 record는 `PascalCase`, 변수와 메서드는 `camelCase`, 상수는 `UPPER_SNAKE_CASE`를 사용합니다.
- 메서드 이름은 `createOrder`, `findProduct`처럼 동사로 시작합니다.
- 역할을 드러내는 접미사를 사용합니다: `Controller`, `Service`, `Repository`, `Request`, `Response`.
- Controller는 HTTP 입출력, Service는 유스케이스, Repository는 영속성 책임을 갖습니다.
- 서비스 간 데이터베이스 테이블을 직접 조회하지 않고 API 또는 이벤트 계약을 사용합니다.
- 공개 API 변경 시 요청·응답 예시와 영향 범위를 함께 문서화합니다.

## 6. Python/FastAPI 규칙

- Python 파일·함수·변수는 `snake_case`, 클래스는 `PascalCase`, 상수는 `UPPER_SNAKE_CASE`를 사용합니다.
- API 스키마는 Pydantic 모델로 명시합니다.
- 라우터, 유스케이스, 외부 인프라 연동 책임을 분리합니다.
- 모델 추론이나 외부 I/O를 라우터 함수에 직접 누적하지 않습니다.

## 7. 포맷과 구조

- UTF-8, LF, 파일 끝 개행을 사용합니다. YAML은 공백 2칸으로 들여씁니다.
- 새 Spring 서비스는 `<service>/src/main/java`와 `<service>/src/main/resources` 구조를 따릅니다.
- 테스트는 각 모듈의 `src/test` 또는 `tests` 아래에 둡니다.
- 공통 설정은 Config Server에 두되, 비밀값은 환경 변수로만 주입합니다.

## 8. 커밋 전 확인

```text
[ ] 브랜치명이 <작업유형>/<기능명> 형식인가?
[ ] 한 커밋에 하나의 작업 목적만 포함했는가?
[ ] 실행·테스트·정적 검증이 성공했는가?
[ ] 디버그 로그와 사용하지 않는 코드가 제거되었는가?
[ ] API Key, 비밀번호, 토큰, 개인정보가 없는가?
[ ] 환경 변수나 실행 방법 변경을 문서에 반영했는가?
[ ] 커밋 제목과 본문이 규칙을 따르는가?
```

기본 검증 명령:

```bash
./gradlew test --no-daemon
docker compose config --quiet
```

FastAPI 모듈 변경 시 해당 서비스의 `requirements.txt`를 설치하고 `pytest`도 실행합니다.
