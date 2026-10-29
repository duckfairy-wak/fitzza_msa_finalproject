# FITZZA-308 Prometheus·Grafana 배포

이 디렉터리는 `kube-prometheus-stack` Helm chart `92.14.1`의 FITZZA 값 파일을
관리한다. EKS·애플리케이션 지표는 Prometheus가 수집하고, RDS·SQS·NAT·CloudFront·WAF
지표는 후속 FITZZA-310에서 Grafana CloudWatch data source로 조회한다.

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

kubectl -n fitzza-monitoring get pods,svc,pvc
kubectl -n fitzza-monitoring get svc -o jsonpath='{range .items[*]}{.metadata.name}{"="}{.spec.type}{"\n"}{end}'
```

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

## 롤백과 저장소

```powershell
helm rollback fitzza-monitoring --namespace fitzza-monitoring --wait --timeout 10m
```

rollback이 불가능하거나 배포를 중단해야 하면 `helm uninstall` 전에 Prometheus PVC와
Retain PV/EBS volume ID를 확인한다. 삭제 후에도 EBS는 자동 삭제되지 않으며 비용이
계속 발생한다. snapshot, 보존 필요성, 대상 volume ID를 확인하고 별도 승인을 받은
경우에만 삭제한다.
