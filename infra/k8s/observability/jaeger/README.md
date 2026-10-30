# EKS Jaeger 파일럿

지원되는 Jaeger v2 이미지 `cr.jaegertracing.io/jaegertracing/jaeger:2.22.0`을 기존
`fitzza` namespace에 배포한다. Jaeger v1은 EOL이므로 운영 파일럿에도 사용하지 않는다.
애플리케이션 배포와 별도로 관리하며 기본 prod/delivery overlay에는 포함하지 않는다.
FITZZA-303에서 이 메모리 기반 파일럿과 운영 샘플링 `0.1` 적용을 승인했다.

## 용량과 저장 정책

- Pod 1개, requests CPU 50m / 메모리 128Mi, limits CPU 500m / 메모리 512Mi.
- 메모리에 최대 1,000개 trace를 저장한다. 시간 기준 보존 정책은 없으며 재시작,
  재배포, 노드 축소 시 모두 사라진다. trace 개수 제한은 메모리 사용량 상한을 보장하지 않는다.
- PVC, LoadBalancer, Ingress를 생성하지 않는다. 장기 보관이 필요하면 별도 저장소와
  보존 기간을 결정해야 한다.
- UI와 OTLP는 ClusterIP로 클러스터 내부에서 접근 가능하다. UI 사용자는 Kubernetes
  RBAC의 `pods/portforward` 권한이 필요하다. namespace 간 트래픽 차단은 제공하지 않는다.

## 배포

AWS CLI 인증 및 EKS 접근 권한이 있는 운영 환경에서 실행한다.

```bash
aws eks update-kubeconfig --name fitzza-prod --region ap-northeast-2 --profile fitzza
kubectl config current-context
kubectl get nodes
kubectl describe nodes
kubectl top nodes
kubectl -n fitzza get pods -o wide
kubectl kustomize infra/k8s/observability/jaeger
kubectl apply --dry-run=server -k infra/k8s/observability/jaeger
```

운영 시간 안에 노드 allocatable과 기존 Pod requests를 비교한다. Jaeger 추가 후에도
CPU 50m, 메모리 128Mi, Pod 슬롯 1개가 확보되어야 한다. `top`이 없으면 Metrics Server
없이 requests와 실제 사용량을 별도로 확인한다. 용량 부족 시 노드를 자동 확장하지 않는다.

```bash
kubectl apply -k infra/k8s/observability/jaeger
kubectl -n fitzza rollout status deployment/jaeger --timeout=180s
kubectl -n fitzza logs deployment/jaeger --tail=50
kubectl -n fitzza port-forward --address 127.0.0.1 service/jaeger 16686:16686
```

마지막 명령을 실행한 상태에서 <http://localhost:16686>에 접속한다.

## 애플리케이션 추적 활성화

Jaeger가 Ready가 된 뒤 현재 운영 ConfigMap의 다른 값을 보존하며 두 키만 추가한다.
동일한 값을 실제 배포 파이프라인의 ConfigMap 원본에도 반영해야 재배포 시 유지된다.
루트 `.env`는 Kubernetes Pod에 자동 전달되지 않는다.

```bash
kubectl -n fitzza edit configmap fitzza-app-config
```

`data`에 추가:

```yaml
MANAGEMENT_OTLP_TRACING_ENDPOINT: http://jaeger:4318/v1/traces
MANAGEMENT_TRACING_SAMPLING_PROBABILITY: "0.1"
```

OTLP 환경 변수를 받는 추적 대상을 한 개씩 재시작한다. Config Server와 Discovery
Service는 제외한다. FastAPI 서비스는 FITZZA-283 코드가 포함된 운영 이미지인지 먼저
확인한다.
각 Deployment가 Ready가 된 뒤 다음 Deployment를 진행한다.

운영 overlay는 단일 replica와 `maxSurge: 0`, `maxUnavailable: 1`을 사용하므로 기존
Pod가 종료된 뒤 새 Pod가 Ready가 될 때까지 해당 서비스 요청이 실패할 수 있다.
특히 `gateway-service` 재시작 중에는 Gateway를 경유하는 API 요청도 실패할 수 있다.
운영 트래픽이 있는 시간은 피하고 승인된 maintenance window에서만 실행한다.

```powershell
$tracedDeployments = @(
  'gateway-service', 'user-service', 'product-service', 'order-service',
  'community-service', 'review-service', 'notification-service',
  'recommendation-service', 'vton-service'
)
foreach ($deploymentName in $tracedDeployments) {
  kubectl -n fitzza rollout restart deployment/$deploymentName
  if ($LASTEXITCODE -ne 0) { throw "Restart failed: $deploymentName" }
  kubectl -n fitzza rollout status deployment/$deploymentName --timeout=900s
  if ($LASTEXITCODE -ne 0) { throw "Rollout failed: $deploymentName" }
}
```

`vton-worker`는 위 반복문에 포함하지 않는다. 먼저 API 등 상위 경로에서 신규 이미지
생성 요청을 차단해 SQS에 새 메시지가 들어오지 않게 한다. 그다음 SQS의 visible
메시지와 in-flight 메시지가 모두 0이며 worker 로그에서 진행 중인 작업이 완료된 것을
확인한 뒤 별도로 재시작한다.

```powershell
kubectl -n fitzza rollout restart deployment/vton-worker
kubectl -n fitzza rollout status deployment/vton-worker --timeout=900s
```

worker는 SIGTERM을 받으면 새 메시지 polling을 멈추고 현재 작업 완료 후 종료하지만,
Deployment에 `terminationGracePeriodSeconds`가 없어 Kubernetes 기본 종료 유예 시간이
적용된다. 이 시간은 이미지 생성 요청의 최대 처리 시간을 수용하지 못할 수 있으므로
drain 확인 전에 재시작하지 않는다. 유예 시간 안에 끝내지 못한 작업이나 visibility
timeout을 넘긴 작업은 SQS에서 재전달될 수 있으며, 반복 실패 시 DLQ로 이동할 수 있다.

Gateway 경유 요청을 반복해 UI에서 서비스 간 trace를 확인한다(샘플링 10%).
애플리케이션 health, OTLP 전송 오류, Jaeger 메모리와 재시작 횟수를 확인한다.
trace 데이터는 개인정보나 토큰을 포함하지 않도록 계측 내용을 검토한다.

## 롤백

ConfigMap 및 배포 원본의 `MANAGEMENT_TRACING_SAMPLING_PROBABILITY`를 `"0.0"`으로
변경하고 위 순서로 애플리케이션을 재시작한다. 이후 Jaeger만 제거한다.

```bash
kubectl delete -k infra/k8s/observability/jaeger
```

삭제하면 메모리의 모든 trace가 사라진다. 기존 서비스, Secret, PVC는 삭제하지 않는다.
