# FITZZA-308 Prometheus·Grafana 배포

이 디렉터리는 `kube-prometheus-stack` Helm chart `92.14.1`의 FITZZA 값 파일을
관리한다. EKS·애플리케이션 지표는 Prometheus가 수집하고, RDS·SQS·NAT·CloudFront·WAF
지표는 Grafana의 선언형 CloudWatch data source로 조회한다. CloudWatch data source는
정적 access key 없이 `fitzza-monitoring-grafana` ServiceAccount의 EKS Pod Identity를
사용한다.

최초 구성은 Prometheus Operator, Prometheus, Grafana, kube-state-metrics,
node-exporter만 설치한다. Alertmanager, Prometheus Adapter, Thanos, Loki,
remote_write, 공개 Ingress와 LoadBalancer는 설치하지 않는다. 설계·용량·비용 기준은
[FITZZA-307 운영 정책](../../../aws/observability/PROMETHEUS_GRAFANA_POLICY.md)을 따른다.

## 사전 조건

- 승인된 운영 시간에 EKS 노드가 하나 이상 `Ready`여야 한다.
- `fitzza-gp3-retain` StorageClass가 존재하고 `Retain`, 암호화 gp3,
  `WaitForFirstConsumer` 설정을 유지해야 한다.
- Helm 3.18 이상과 `kubectl`이 설치되고, 대상 EKS cluster context가 확인되어야 한다.
- server-side dry-run을 실행하려면 `fitzza-monitoring` namespace가 이미 존재해야 한다.
  실제 Helm 설치의 `--create-namespace`는 namespace를 만들 수 있지만, 이 프리플라이트는
  기존 namespace와 API 권한을 먼저 검증한다.
- chart `92.14.1`이 사용하는 컨테이너 이미지가 노드 ARM64 아키텍처를 지원하는지
  실제 pull 전 확인해야 한다.
- Grafana 관리자 Secret은 운영 비밀 저장소에서 생성한다. Secret 값은 저장소, Jira,
  shell history, 로그에 넣지 않는다.
- `grafana-cloudwatch.yaml`의 `GrafanaCloudWatchPodIdentityAssociation`이 별도
  `fitzza-prod-grafana-cloudwatch` 스택으로 배포되어야 한다.
  연결 대상은 `fitzza-monitoring/fitzza-monitoring-grafana`이며 역할은 CloudWatch
  metric 조회만 허용한다.

### Pod Identity Agent 확인

CloudFormation의 association은 EKS Pod Identity Agent를 설치하지 않는다. 전용 스택을
배포하기 전에 Agent DaemonSet의 Ready 수가 스케줄 대상 노드 수와 같은지 확인한다.

```powershell
$Agent = kubectl get daemonset eks-pod-identity-agent -n kube-system -o json |
  ConvertFrom-Json

if (($Agent.status.desiredNumberScheduled -eq 0) -or
    ($Agent.status.numberReady -ne $Agent.status.desiredNumberScheduled) -or
    ($Agent.status.numberAvailable -ne $Agent.status.desiredNumberScheduled)) {
  throw "eks-pod-identity-agent가 모든 대상 노드에서 Ready가 아닙니다."
}

kubectl get pods -n kube-system `
  -l app.kubernetes.io/name=eks-pod-identity-agent `
  -o wide
```

노드 추가·교체 후에도 같은 검사를 반복한다. Agent가 없는 노드에서는 해당 노드에
스케줄된 Grafana Pod가 Pod Identity 자격 증명을 받을 수 없다.

### foundation 스택에서 전용 스택으로 이전

기존 `fitzza-prod-foundation` 스택이 Grafana 역할과 association을 관리하는 환경은
두 스택이 같은 고정 `RoleName`인 `fitzza-prod-grafana-cloudwatch-read`를 동시에 소유할
수 없다. 따라서 전용 스택을 먼저 만들면 안 되며 다음 순서를 지킨다.

먼저 기존 소유 여부를 확인한다. 결과가 없으면 이 이전 단계는 건너뛰고 전용 스택을
바로 배포한다.

```powershell
aws cloudformation describe-stack-resources `
  --stack-name fitzza-prod-foundation `
  --profile fitzza `
  --region ap-northeast-2 `
  --query "StackResources[?LogicalResourceId=='GrafanaCloudWatchRole' || LogicalResourceId=='GrafanaCloudWatchPodIdentityAssociation'].[LogicalResourceId,ResourceStatus,PhysicalResourceId]" `
  --output table
```

리소스가 나오면 다음 순서로 이전한다.

1. Grafana 리소스를 제거한 최신 `foundation.yaml`로 foundation 변경 집합을 생성하되
   아직 실행하지 않는다.
2. 변경 집합을 조회해 `GrafanaCloudWatchRole`과
   `GrafanaCloudWatchPodIdentityAssociation`의 `Remove` 외에 다른 변경이 없는지
   확인한다. 다른 리소스의 변경·교체·삭제가 있으면 실행하지 않는다.
3. 승인된 변경 집합 ARN으로 아래 명령을 실행하고 foundation 업데이트 완료를
   기다린다.

```powershell
$FoundationChangeSetArn = '<검토하고 승인한 foundation 변경 집합 ARN>'

aws cloudformation execute-change-set `
  --change-set-name $FoundationChangeSetArn `
  --profile fitzza `
  --region ap-northeast-2

aws cloudformation wait stack-update-complete `
  --stack-name fitzza-prod-foundation `
  --profile fitzza `
  --region ap-northeast-2

aws cloudformation describe-stacks `
  --stack-name fitzza-prod-foundation `
  --profile fitzza `
  --region ap-northeast-2 `
  --query 'Stacks[0].StackStatus' `
  --output text
```

`UPDATE_COMPLETE`를 확인한 뒤에만 전용 스택을 생성한다. foundation에서 association이
제거된 시점부터 전용 스택과 새 association이 준비되고 Grafana가 재시작될 때까지
CloudWatch 쿼리는 중단될 수 있다. Prometheus 수집에는 영향이 없지만 승인된 운영
시간에 작업하고 두 단계 사이의 시간을 최소화한다.

```powershell
aws cloudformation deploy `
  --stack-name fitzza-prod-grafana-cloudwatch `
  --template-file infra/aws/cloudformation/grafana-cloudwatch.yaml `
  --capabilities CAPABILITY_NAMED_IAM `
  --profile fitzza `
  --region ap-northeast-2
```

전용 스택 생성 후 association을 확인한다.

```powershell
aws eks list-pod-identity-associations `
  --cluster-name fitzza-prod `
  --namespace fitzza-monitoring `
  --service-account fitzza-monitoring-grafana `
  --profile fitzza `
  --region ap-northeast-2 `
  --query 'associations[].{Id:associationId,Namespace:namespace,ServiceAccount:serviceAccount}' `
  --output table
```

foundation 변경이 실패하면 CloudFormation의 rollback 완료를 확인하고 전용 스택을
생성하지 않는다. foundation 제거는 완료됐지만 전용 스택 생성이 실패하면 실패 이벤트와
rollback 상태를 먼저 확인한다. 전용 스택이 `ROLLBACK_COMPLETE`라면 정확한 스택 이름을
확인해 삭제하고 삭제 완료를 기다린 다음, 이전 foundation 템플릿으로 Grafana 역할과
association을 복구한다.

```powershell
aws cloudformation delete-stack `
  --stack-name fitzza-prod-grafana-cloudwatch `
  --profile fitzza `
  --region ap-northeast-2
aws cloudformation wait stack-delete-complete `
  --stack-name fitzza-prod-grafana-cloudwatch `
  --profile fitzza `
  --region ap-northeast-2
```

전용 스택 생성 후 운영 검증에서 복구가 필요할 때도 고정 RoleName 충돌을 피하기 위해
전용 스택을 먼저 삭제하고, 삭제 완료 후 이전 foundation 템플릿을 적용한다. 복구된
association을 확인하고 아래 Grafana 재시작과 metric query 검증을 다시 수행한다.

Grafana Secret은 반드시 아래 키만 사용한다.

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: fitzza-grafana-admin
  namespace: fitzza-monitoring
type: Opaque
stringData:
  admin-user: CHANGE_ME
  admin-password: CHANGE_ME
```

위 예시는 키 계약 설명용이다. `CHANGE_ME` 값을 적용하거나 Git에 커밋하면 안 된다.

## 배포 전 용량 게이트

`metrics-server`는 이 배포의 선행 조건이 아니다. `kubectl top`을 사용할 수 없으면
requests/limits와 노드 allocatable을 기준으로 판단한다.

```powershell
aws eks update-kubeconfig --name fitzza-prod --region ap-northeast-2 --profile fitzza
kubectl config current-context
kubectl wait --for=condition=Ready node --all --timeout=10m
kubectl get storageclass fitzza-gp3-retain
kubectl get storageclass fitzza-gp3-retain -o jsonpath='{.reclaimPolicy}{"\n"}{.volumeBindingMode}{"\n"}'
kubectl describe nodes
kubectl -n fitzza get pods -o wide
```

기존 workload와 시스템 Pod의 requests, limits, Pod 수를 합산한다. 이 stack의
steady-state requests 상한은 CPU 260m, 메모리 672Mi다. Alertmanager는 비활성이다.
DaemonSet인 node-exporter는 노드당 CPU 10m, 메모리 32Mi다. 추가 후에도 node
allocatable CPU·메모리 각각 20%와 Pod 슬롯이 남지 않으면 설치하지 않는다.

## 렌더링과 server-side 검증

저장소의 안전한 기본 실행기는 `scripts/deploy_prometheus_stack.ps1`다. 기본 동작은
읽기·렌더링·server-side dry-run뿐이며, 실제 설치는 `-Apply`를 명시해야 한다.

Helm repository를 추가하고, 적용 전에 출력 manifest를 검토한다.

```powershell
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update
helm show values prometheus-community/kube-prometheus-stack --version 92.14.1 | Out-Null
helm template fitzza-monitoring prometheus-community/kube-prometheus-stack `
  --version 92.14.1 `
  --namespace fitzza-monitoring `
  --create-namespace `
  --include-crds `
  --values infra/k8s/observability/prometheus/values.yaml `
  --output-dir .tmp/fitzza-monitoring-render
kubectl create --dry-run=client `
  --filename .tmp/fitzza-monitoring-render/kube-prometheus-stack/crds `
  --output name
kubectl get customresourcedefinition
```

먼저 렌더된 CRD의 client-side 검증을 통과해야 한다. 위 CRD 이름이 클러스터의
`kubectl get customresourcedefinition` 결과에 모두 존재할 때만 전체 manifest의
server-side dry-run을 실행한다.

```powershell
kubectl apply --dry-run=server --namespace fitzza-monitoring `
  --filename .tmp/fitzza-monitoring-render/kube-prometheus-stack
```

최초 설치라 필요한 CRD가 아직 없다면 전체 server-side dry-run을 건너뛴다. 승인된
`helm upgrade --install`이 CRD를 먼저 설치하며, 이후 upgrade부터 전체 server-side
dry-run을 실행한다. dry-run을 위해 CRD만 별도로 클러스터에 적용하지 않는다.

또는 저장소 루트에서 다음처럼 실행한다.

```powershell
.\scripts\deploy_prometheus_stack.ps1
```

검토할 항목:

- Prometheus, Grafana Service가 모두 `ClusterIP`이고 Ingress/LoadBalancer가 없는지
- Prometheus PVC가 10Gi `fitzza-gp3-retain`인지
- retention이 7일/8GB, scrape/evaluation interval이 60초인지
- Grafana Secret 값이 렌더 결과나 터미널 출력에 없는지
- Operator, kube-state-metrics, node-exporter의 requests/limits가 정책 상한 이하인지

`kube-state-metrics`는 `registry.k8s.io`의 리전별 S3 전달 경로에서 발생하는 pull
실패를 피하기 위해 Kubernetes production 이미지의 공식 아시아 Artifact Registry
경로를 사용한다. 이미지 버전은 차트의 app version과 같은 `v2.20.0`으로 고정한다.

`.tmp/` 렌더 결과는 검증 후 삭제한다. Secret이 포함된 파일이나 command output은
저장하지 않는다.

## 설치와 확인

사전 용량 게이트 및 manifest 검토가 통과한 승인된 운영 시간에만 설치한다.

```powershell
helm upgrade --install fitzza-monitoring prometheus-community/kube-prometheus-stack `
  --version 92.14.1 `
  --namespace fitzza-monitoring `
  --create-namespace `
  --values infra/k8s/observability/prometheus/values.yaml `
  --wait --timeout 10m

kubectl apply `
  --filename infra/k8s/observability/prometheus/gateway-service-monitor.yaml

kubectl -n fitzza-monitoring get pods,svc,pvc
kubectl -n fitzza-monitoring get servicemonitor gateway-service
kubectl -n fitzza-monitoring get svc -o jsonpath='{range .items[*]}{.metadata.name}{"="}{.spec.type}{"\n"}{end}'

# 기존 Pod에도 새 association의 자격 증명 설정이 주입되도록 반드시 재생성한다.
kubectl -n fitzza-monitoring rollout restart deployment/fitzza-monitoring-grafana
kubectl -n fitzza-monitoring rollout status `
  deployment/fitzza-monitoring-grafana `
  --timeout=3m
```

association을 새로 만들거나 교체한 뒤에는 변경 없는 `helm upgrade --install`만으로
기존 Pod가 재생성된다고 가정하지 않는다. Pod Identity 환경 변수는 새 Pod 생성 시
주입되므로 위 `rollout restart`와 완료 확인이 필수다.

Prometheus PVC 이름은 release/chart 버전에 따라 달라질 수 있으므로 특정 이름을
가정하지 말고 위 `kubectl -n fitzza-monitoring get pvc` 결과에서 확인한다.

Prometheus와 Grafana는 공개하지 않는다. 승인된 운영자만 loopback port-forward를
사용한다.

```powershell
kubectl -n fitzza-monitoring port-forward --address 127.0.0.1 service/fitzza-monitoring-kube-prometheus-prometheus 9090:9090
kubectl -n fitzza-monitoring port-forward --address 127.0.0.1 service/fitzza-monitoring-grafana 3000:80
```

Prometheus Targets에서 kubelet, node-exporter, kube-state-metrics가 `UP`인지
확인한다. 실패 시 대상 URL, 인증서, RBAC, node-exporter DaemonSet 스케줄 상태를
확인하고 무단으로 `--resolve-conflicts`나 공개 Service를 추가하지 않는다.

Grafana의 Connections > Data sources에서 Prometheus와 CloudWatch가 모두 provisioned
상태인지 확인한다. CloudWatch는 기본 리전 `ap-northeast-2`, 인증 방식 `AWS SDK
Default`여야 한다. 메트릭 전용 역할이므로 CloudWatch Logs 조회는 허용하지 않는다.
CloudWatch 패널의 기본 refresh는 5분으로 유지한다. 서울 리전의 AWS 리소스 지표는
기본 리전을 사용하고, CloudFront 및 CloudFront 범위의 WAF 지표를 조회하는 각 쿼리는
리전을 `us-east-1`로 선택한다.

```powershell
kubectl -n fitzza-monitoring get serviceaccount fitzza-monitoring-grafana
kubectl -n fitzza-monitoring get pods -l app.kubernetes.io/name=grafana -o wide
kubectl -n fitzza-monitoring get deployment fitzza-monitoring-grafana `
  -o jsonpath='{.status.readyReplicas}{"/"}{.status.replicas}{" Ready"}{"\n"}'
kubectl -n fitzza-monitoring get pods -l app.kubernetes.io/name=grafana `
  -o jsonpath='{range .items[*].spec.containers[?(@.name=="grafana")].env[*]}{.name}{"\n"}{end}' |
  Select-String -Pattern 'AWS_CONTAINER_CREDENTIALS_FULL_URI|AWS_CONTAINER_AUTHORIZATION_TOKEN_FILE'
kubectl -n fitzza-monitoring logs deployment/fitzza-monitoring-grafana --since=10m |
  Select-String -Pattern 'CloudWatch|AccessDenied|NoCredentialProviders|WebIdentityErr'
```

마지막으로 Grafana의 **Explore**에서 CloudWatch data source를 선택하고 실제 metric
query를 실행한다. 서울 리전 검증은 `Region=ap-northeast-2`, `Namespace=AWS/EC2`,
`Metric=CPUUtilization`, 현재 노드의 `InstanceId`, `Statistic=Average`로 최근 15분을
조회해 시계열 데이터가 반환되는지 확인한다. 이어 CloudFront 또는 CloudFront 범위
WAF 쿼리는 `Region=us-east-1`로 실행한다. association 존재 여부만 확인하거나
CloudWatch Logs 권한까지 검사하는 `Save & test` 결과만으로 metric 조회 성공을
판정하지 않는다. 실제 metric query 성공과 Grafana 로그에 자격 증명·권한 오류가
없는 것을 함께 확인해야 배포 완료다.

## 롤백과 저장소

```powershell
helm rollback fitzza-monitoring --namespace fitzza-monitoring --wait --timeout 10m
```

rollback이 불가능하거나 배포를 중단해야 하면 `helm uninstall` 전에 Prometheus PVC와
Retain PV/EBS volume ID를 확인한다. 삭제 후에도 EBS는 자동 삭제되지 않으며 비용이
계속 발생한다. snapshot, 보존 필요성, 대상 volume ID를 확인하고 별도 승인을 받은
경우에만 삭제한다.
