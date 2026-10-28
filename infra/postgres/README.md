# PostgreSQL 서비스별 DB 계정

`init.sql`은 Compose Postgres **최초 기동** 시 스키마만 만든다.
서비스 전용 DB 계정은 `<스키마>_app`(예: `product_service_app`)이며, 스크립트로 별도 생성한다.

| 역할 | 스키마 | env (비밀번호) |
| --- | --- | --- |
| `user_service_app` | `user_service` | `USER_SERVICE_DB_PASSWORD` |
| `product_service_app` | `product_service` | `PRODUCT_SERVICE_DB_PASSWORD` |
| `order_service_app` | `order_service` | `ORDER_SERVICE_DB_PASSWORD` |
| `community_service_app` | `community_service` | `COMMUNITY_SERVICE_DB_PASSWORD` |
| `review_service_app` | `review_service` | `REVIEW_SERVICE_DB_PASSWORD` |
| `notification_service_app` | `notification_service` | `NOTIFICATION_SERVICE_DB_PASSWORD` |

Java 6개 서비스는 서비스별 `*_DB_USER`/`*_DB_PASSWORD`를 필수로 사용하며, 공용 `POSTGRES_USER`/`POSTGRES_PASSWORD`로 fallback하지 않는다. Kubernetes에서는 이 값을 `fitzza-db-secrets`에 보관하고 각 Deployment에 `SPRING_DATASOURCE_USERNAME`/`SPRING_DATASOURCE_PASSWORD`로 주입한다.

## 서비스 계정 적용

`\ir`가 같은 디렉터리의 `service-account.psql`을 참조하므로 `infra/postgres`에서 실행한다. psql 15+ 필요.

```bash
cd infra/postgres
export USER_SERVICE_DB_PASSWORD="${USER_SERVICE_DB_PASSWORD:-fitzza_local}"
export PRODUCT_SERVICE_DB_PASSWORD="${PRODUCT_SERVICE_DB_PASSWORD:-fitzza_local}"
export ORDER_SERVICE_DB_PASSWORD="${ORDER_SERVICE_DB_PASSWORD:-fitzza_local}"
export COMMUNITY_SERVICE_DB_PASSWORD="${COMMUNITY_SERVICE_DB_PASSWORD:-fitzza_local}"
export REVIEW_SERVICE_DB_PASSWORD="${REVIEW_SERVICE_DB_PASSWORD:-fitzza_local}"
export NOTIFICATION_SERVICE_DB_PASSWORD="${NOTIFICATION_SERVICE_DB_PASSWORD:-fitzza_local}"
psql -v ON_ERROR_STOP=1 -h localhost -U "${POSTGRES_USER:-fitzza}" -d "${POSTGRES_DB:-fitzza}" \
  -f service-accounts.sql
```

비밀번호 env가 없는 서비스는 건너뛴다. 다시 실행해도 된다(비밀번호 갱신·기존 테이블 소유권 이전).

## 운영 검증과 롤백

1. 서비스를 하나씩 재배포하고 Ready 1/1과 Flyway 성공을 확인한다.
2. 각 계정이 자기 스키마에는 접속하고 다른 서비스 스키마에는 접근하지 못하는지 확인한다.
3. 롤백은 서비스별 Secret의 직전 버전을 복원한 뒤 해당 Deployment만 재시작한다. 공용 DB 계정 fallback을 다시 추가하는 방식으로 롤백하지 않는다.
4. 비밀번호 값은 코드·명령행·로그·Jira에 남기지 않고, 검증 결과와 Secret 버전만 기록한다.
