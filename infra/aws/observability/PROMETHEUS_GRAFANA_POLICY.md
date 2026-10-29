# FITZZA-307 Prometheus·Grafana 아키텍처와 운영 정책

이 문서는 FITZZA-307의 결정 기록이다. EKS와 애플리케이션 지표는
Prometheus가 수집하고, AWS 관리형 서비스 지표는 CloudWatch를 Grafana에서 직접
조회한다. 실제 Helm 배포와 값 검증은 FITZZA-308에서 수행한다.

## 결정 요약

| 항목 | 결정 | 근거 |
| --- | --- | --- |
| EKS·애플리케이션 지표 | 자체 운영 Prometheus | Pod·노드·JVM·FastAPI 지표를 연속 시계열로 보관하며 CloudWatch 중복 수집을 피한다. |
| AWS 관리형 서비스 지표 | Grafana CloudWatch data source | RDS, SQS, NAT Gateway, CloudFront, WAF의 기본 지표를 다시 Prometheus로 복제하지 않는다. |
| Grafana | EKS 내부 배포, 두 data source 통합 | 단일 화면에서 Prometheus와 CloudWatch를 조회하되 원본의 책임은 분리한다. |
| metrics-server | 기본 구성에서 제외 | Grafana 시계열 수집에는 필요하지 않다. HPA 또는 `kubectl top`이 필요할 때만 별도 승인 후 설치한다. |
| 최초 scrape 주기 | 60초 | 단일 노드 파일럿의 저장 공간과 수집 부하를 우선 제한한다. 필요한 지표만 예외적으로 단축한다. |
| 최초 보존 기간 | 7일 | 파일럿 기준선 확인에 필요한 기간을 확보하면서 EBS 사용량을 제한한다. |
| Prometheus PVC | 암호화 gp3 10Gi, `fitzza-gp3-retain` 명시 | 기본 StorageClass가 없으며 기존 보존 정책과 일치시킨다. 확장은 측정 후 승인한다. |
| 외부 접근 | ClusterIP와 로컬 port-forward | 공개 LoadBalancer·Ingress와 익명 접근을 만들지 않는다. |
| Container Insights | 기본 비활성 | 같은 EKS CPU·메모리 지표의 중복 수집과 CloudWatch 비용을 피한다. |

## 데이터 흐름과 책임 경계

```text
EKS node / kube-state-metrics / application /metrics
                         |
                         v
                    Prometheus ----+
                                    |
RDS / SQS / NAT / CloudFront / WAF  |     +---------+
                         |          +---->| Grafana |
                         v                +---------+
                     CloudWatch --------------^
```

- Prometheus는 노드와 Pod 자원, 재시작·상태, Spring Boot Actuator/Micrometer,
  FastAPI의 애플리케이션 지표를 소유한다.
- CloudWatch는 AWS가 기본 제공하는 관리형 서비스 지표와 기존 EKS control plane
  로그를 소유한다. Grafana는 읽기 전용 권한으로 이를 조회한다.
- Grafana는 표시 계층이며 원본 지표를 복제하거나 장기 보관하지 않는다.
- 로그와 trace는 이 범위에 포함하지 않는다. 기존 CloudWatch Logs와 Jaeger 정책을
  유지한다.

## kube-prometheus-stack 구성 범위

FITZZA-308은 다음 구성요소만 검토·배포한다.

- Prometheus Operator와 Prometheus server
- Grafana
- kube-state-metrics
- node-exporter
- Alertmanager: FITZZA-178 알림 경로와 수신자가 확정될 때 활성화한다. 그전에는
  비활성 또는 최소 replica로 두며 외부 알림을 발송하지 않는다.

Prometheus Adapter, Thanos, Loki, 원격 저장소, 공개 Ingress는 최초 구성에서 제외한다.
필요성이 확인되면 별도 비용·보안 검토를 거친다.

## 단일 노드 용량 게이트

현재 운영 계획은 ARM64 `t4g.large` 한 대이고, 기존 파일럿 13개 Pod의 정적 requests
합계는 CPU 1400m, 메모리 2752Mi다. 이 값만으로는 DaemonSet과 시스템 Pod를 포함한
실제 배치 가능 용량을 판단할 수 없다.

FITZZA-308의 최초 values 후보는 다음 합계를 넘지 않도록 조정한다. 이는 성능 보장이
아닌 배포 전 상한이며, 실제 사용량을 측정해 올리거나 내린다.

| 구성요소 | CPU request 상한 | Memory request 상한 | CPU limit 상한 | Memory limit 상한 |
| --- | ---: | ---: | ---: | ---: |
| Prometheus | 150m | 384Mi | 500m | 768Mi |
| Grafana | 50m | 128Mi | 200m | 256Mi |
| Prometheus Operator | 25m | 64Mi | 100m | 128Mi |
| kube-state-metrics | 25m | 64Mi | 100m | 128Mi |
| node-exporter(노드당) | 10m | 32Mi | 50m | 64Mi |
| Alertmanager(활성화 시) | 25m | 64Mi | 100m | 128Mi |
| 합계(노드 1대, Alertmanager 포함) | 285m | 736Mi | 1050m | 1472Mi |

배포는 승인된 작업 시간에 다음 순서로 진행한다.

1. `foundation.yaml`이 정의한 `fitzza-prod-node-scaler`를 `{"desiredSize":1}`로
   호출한다. 템플릿의 기본 `DesiredSize: 0`은 변경하지 않는다.
2. node group의 desired size가 1인지 확인하고,
   `kubectl wait --for=condition=Ready node --all --timeout=10m`으로 노드가 `Ready`가
   될 때까지 기다린다. 실패하거나 timeout이면 배포를 중단한다.
3. `kubectl describe node`의 allocatable과 시스템 Pod를 포함한 전체 Pod requests,
   limits, Pod 수를 확인한다.
4. 모니터링 스택을 추가한 뒤에도 allocatable CPU와 메모리 각각 20% 이상이 남고
   최대 Pod 수를 넘지 않을 때만 Prometheus와 Grafana를 배포한다.

용량 조건을 만족하지 않으면 다음 순서로 중단·축소한다.

1. Alertmanager를 비활성화한다.
2. 불필요한 기본 scrape target과 recording rule을 줄인다.
3. 기존 워크로드 requests의 근거를 재측정한다.
4. 그래도 20% 여유가 없으면 노드 증설 또는 별도 모니터링 방식을 승인받기 전까지
   배포하지 않는다.

limits 합계는 모든 구성요소가 동시에 최대로 동작할 때 노드에 줄 수 있는 위험 상한이다.
기존 워크로드 limits와 합산한 동시 최대 사용량도 배포 전 확인한다. CPU throttling,
OOM, scrape 누락이 발생하면 requests와 limits를 함께 재산정하며, limit만 높여 노드
과할당을 숨기지 않는다.

## 보존·저장소 정책

- 전역 scrape interval과 evaluation interval은 60초로 시작한다.
- Prometheus retention time은 7일, retention size는 PVC의 80%보다 작게 설정해
  파일시스템 여유를 남긴다.
- PVC는 `fitzza-gp3-retain` 10Gi를 명시한다. 사용률 70%는 검토, 85%는 수집 범위
  축소 또는 확장 승인 기준으로 사용한다.
- 보존 기간을 15일까지 늘리거나 PVC를 20Gi로 확장하는 변경은 7일간의 실제
  ingest rate, series 수, WAL 증가량과 예상 EBS 비용을 Jira에 기록한 뒤 승인한다.
- `Retain` 정책이므로 Helm release/PVC 삭제 후에도 PV와 EBS 볼륨이 남아 비용이
  계속 발생할 수 있다. 삭제는 snapshot 필요 여부, 연결된 PV/PVC, volume ID를
  확인하고 별도 승인한다.
- Grafana 대시보드와 data source 설정은 선언형 values 또는 provisioning 파일로
  저장한다. Grafana 내부 DB만을 유일한 백업으로 사용하지 않는다.

## 비용 기준

자체 Prometheus에는 CloudWatch custom metric의 지표당 과금이 없지만 무료는 아니다.
노드 CPU·메모리 점유, gp3 EBS, snapshot, 운영 시간이 비용 요소다. CloudWatch data
source는 기존 AWS 관리형 지표를 조회하며 API 호출과 대시보드 새로고침 빈도가 비용에
영향을 줄 수 있다.

비용 중복을 막기 위해 다음을 지킨다.

- EKS 노드·Pod CPU/메모리를 Prometheus와 Container Insights에 동시에 신규 수집하지
  않는다.
- AWS 관리형 서비스 기본 지표를 exporter로 다시 복제하지 않는다.
- Grafana CloudWatch 패널의 기본 refresh는 5분으로 시작하고, 장애 대응 화면만
  승인된 시간 동안 단축한다.
- 고해상도 custom metric, detailed monitoring, remote_write는 별도 승인 없이는
  활성화하지 않는다.
- FITZZA-312에서 7일 기준 EBS 사용량, series 수, query/API 사용량과 노드 여유를
  비용 기준선으로 기록한다.

## cardinality와 개인정보 정책

허용 label은 서비스, namespace, workload, pod, container, HTTP method, 정규화된
route, status code처럼 값의 종류가 제한된 운영 차원으로 한정한다.

다음 값은 metric 이름, label 이름·값에 넣지 않는다.

- 사용자 ID, 로그인 ID, 이메일, 전화번호, 주소, 토큰, 세션 ID
- 주문·민원·상품 등 개별 도메인 객체 ID
- 원문 URL, query string, request/response body, 예외 stack trace
- timestamp, UUID, 임의 생성값, SQL문

HTTP path는 `/users/{id}`처럼 route template으로 정규화한다. 새 metric은 label별 예상
값 개수와 곱집합을 PR에 기록하고, 무제한 증가 가능성이 있으면 배포하지 않는다.

## 접근 통제

- Prometheus, Grafana, Alertmanager Service는 ClusterIP로 둔다.
- 운영자는 승인된 Kubernetes RBAC 자격으로 `127.0.0.1`에 port-forward한다.
- Grafana 익명 로그인과 기본 admin 비밀번호 사용을 금지한다. 자격정보는 Kubernetes
  Secret 또는 승인된 비밀 저장소에서 주입하며 저장소에 기록하지 않는다.
- Grafana의 CloudWatch 접근 권한은 조회에 필요한 action과 대상 리전으로 제한하고
  변경·삭제 권한을 부여하지 않는다.
- 외부 공유, public dashboard, LoadBalancer, Ingress는 별도 인증·TLS·비용 검토 전
  금지한다.

## 배포 승인과 롤백

FITZZA-308 배포 전 다음 증적을 Jira에 첨부한다.

1. 실제 node allocatable, 시스템 Pod 포함 requests 합계, 배포 후 예상 여유
2. ARM64 이미지 지원 여부와 기존 collector/ServiceMonitor 충돌 여부
3. StorageClass 존재, PVC 크기, reclaim policy, 예상 EBS 비용
4. 렌더링한 Helm manifest와 RBAC·Secret·Service 노출 검토 결과
5. 승인된 작업 시간, 담당자, 중단 기준, 복구 명령

배포 후 Pending Pod, 지속적인 OOM/throttling, scrape 실패, 기존 서비스 성능 저하,
20% 용량 여유 미달 중 하나가 발생하면 release를 이전 values로 되돌리거나 제거한다.
제거 후에도 retained PV/EBS는 자동 삭제하지 않으며, 대시보드 provisioning 파일과
검증 증적을 보존한 뒤 비용 소유자가 삭제 여부를 결정한다.

## 후속 과업 인수 조건

- FITZZA-308: 이 문서의 용량 게이트와 보안 범위 안에서 stack과 PVC를 배포한다.
- FITZZA-309: Spring/FastAPI metric과 label cardinality를 검증한다.
- FITZZA-310: 읽기 전용 CloudWatch data source와 refresh 주기를 구성한다.
- FITZZA-177·178: 통합 dashboard와 승인된 alert를 구성한다.
- FITZZA-311: provisioning 백업, 접근권한, retained EBS 복구·삭제 절차를 검증한다.
- FITZZA-312: 7일 운영 데이터로 용량·비용 기준선을 갱신한다.

