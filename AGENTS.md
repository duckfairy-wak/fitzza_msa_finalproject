# Fitzza AI 작업 지침

이 파일은 저장소에서 작업하는 AI 코딩 도구의 공통 진입점입니다.

## 반드시 읽을 문서

작업 전에 [CONTRIBUTING.md](CONTRIBUTING.md)를 읽고 브랜치, 커밋, PR, 코드 규칙을 준수합니다. 규칙의 원문은 문서 상단에 연결된 Notion 페이지입니다.

## 작업 규칙

- Java 21, Gradle Wrapper, Spring Boot 멀티프로젝트 구성을 유지합니다. Maven 파일을 만들지 않습니다.
- 새 작업은 최신 `develop`에서 `<작업유형>/<kebab-case 기능명>` 브랜치로 시작합니다.
- `main` 또는 `develop`에 직접 커밋하거나 push하지 않습니다. 초기 `develop` 생성만 예외입니다.
- 한 커밋에는 하나의 목적만 담고 `[작업유형]_DD/기능명` 제목 및 작업·이유·검증 본문을 작성합니다.
- PR 대상은 `develop`이며 `.github/PULL_REQUEST_TEMPLATE.md`를 사용합니다.
- 기존 사용자 변경을 보존하고 관련 없는 파일을 수정하거나 되돌리지 않습니다.
- 비밀값, 인증정보, 개인정보를 코드·로그·문서에 넣지 않습니다.
- 서비스는 자신의 데이터만 소유하며 다른 서비스의 스키마를 직접 읽지 않습니다.

## 네이밍 요약

- Java: 클래스 `PascalCase`, 변수·메서드 `camelCase`, 상수 `UPPER_SNAKE_CASE`, 패키지 소문자.
- Python: 클래스 `PascalCase`, 파일·함수·변수 `snake_case`, 상수 `UPPER_SNAKE_CASE`.
- 이름은 역할이 드러나게 쓰고 함수·메서드는 한 가지 책임만 갖게 합니다.
- 설명이 필요한 의도와 제약만 주석으로 남기며 코드를 반복 설명하지 않습니다.

## 검증

- Java 변경: `./gradlew test --no-daemon`
- Compose 변경: `docker compose config --quiet`
- Python 변경: 해당 FastAPI 서비스의 `pytest`
- 실행 방법이나 환경 변수가 바뀌면 README와 `.env.example`을 함께 갱신합니다.
