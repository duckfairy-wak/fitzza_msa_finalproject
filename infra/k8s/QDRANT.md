# Qdrant 운영 계약

FITZZA-174의 범위는 EKS 내부 단일 Qdrant와 영속 스토리지입니다. Qdrant는 `ClusterIP`로만 노출하고, `fitzza.io/qdrant-client: "true"` 라벨이 있는 Pod만 NetworkPolicy를 통해 접근합니다. VPC CNI의 NetworkPolicy 기능이 먼저 활성화되어 있어야 합니다.

## 컬렉션 계약

| 항목 | 값 |
| --- | --- |
| 물리 컬렉션 | `fitzza_products_v1` |
| 읽기용 별칭 | `fitzza_products_current` |
| 벡터 | FashionCLIP 512차원, Cosine |
| Point 단위 | 상품-색상-이미지 조합 하나 |
| Point ID | `product_id`, `color_variant`, `image_url`을 정규화한 문자열의 UUIDv5 |

필수 payload와 권장 인덱스는 다음과 같습니다.

- `product_id`: keyword
- `color_variant`: keyword
- `normalized_color`: keyword
- `brand`: keyword
- `category`: keyword
- `price`: integer
- `image_url`: 저장하되 필터에 사용하기 전에는 인덱스를 만들지 않음

운영 컬렉션을 삭제 후 재생성하지 않습니다. 새 버전 컬렉션에 적재·검증한 뒤 `fitzza_products_current` 별칭을 원자적으로 변경합니다.

## 배포 및 확인

```powershell
kubectl apply -k infra/k8s/overlays/prod
kubectl -n fitzza rollout status statefulset/qdrant --timeout=300s
kubectl -n fitzza get service qdrant
kubectl -n fitzza get pvc qdrant-storage-qdrant-0
kubectl -n fitzza port-forward service/qdrant 6333:6333
python scripts/qdrant_smoke_test.py
```

`qdrant` Service는 `ClusterIP`여야 하며 외부 LoadBalancer나 NodePort가 생기면 안 됩니다. 애플리케이션 로그는 표준 출력으로 기록되어 EKS의 CloudWatch 로그 수집 경로와 호환됩니다.

단일 노드 운영의 CPU 예약량을 줄이기 위해 Qdrant CPU request는 100m, limit은 1 core로
유지한다. request 조정은 CPU 상한을 낮추지 않으므로 검색·색인 시 1 core까지 burst할 수
있다. 지속적인 throttling, readiness 실패 또는 색인 지연이 관측되면 request를 250m로
되돌리고 노드 용량을 재검토한다.

## 스냅샷과 복구

컬렉션 스냅샷 생성:

```powershell
Invoke-RestMethod -Method Post http://localhost:6333/collections/fitzza_products_v1/snapshots
```

반환된 파일 이름으로 스냅샷을 내려받아 버전 관리가 켜진 전용 S3 백업 경로에 복사합니다. Qdrant 버전 호환성 때문에 복구 시 배포 이미지 `v1.15.5`를 유지하고, 업그레이드 전에 공식 호환 범위를 확인합니다.

```powershell
Invoke-WebRequest http://localhost:6333/collections/fitzza_products_v1/snapshots/<snapshot-name> -OutFile <snapshot-name>
aws s3 cp <snapshot-name> s3://<backup-bucket>/qdrant/fitzza_products_v1/
```

복구는 기존 운영 컬렉션을 덮어쓰지 않고 새 컬렉션에서 검증합니다.

```powershell
$body = @{ location = 'https://<signed-snapshot-url>'; priority = 'snapshot' } | ConvertTo-Json
Invoke-RestMethod -Method Put -ContentType application/json -Body $body http://localhost:6333/collections/fitzza_products_restore/snapshots/recover
```

PVC는 암호화된 gp3 20GiB이며 StorageClass의 reclaim policy는 `Retain`입니다. 노드가 0대로 축소되어도 EBS 볼륨과 비용은 유지되고, Qdrant는 노드가 다시 기동될 때까지 사용할 수 없습니다.

Qdrant를 종료하거나 스택을 삭제하기 전에는 최신 스냅샷을 S3에 복사하고 복구 가능성을 확인합니다. 이후 PVC/PV를 조회해 Retain으로 남은 PV와 연결된 EBS 볼륨을 식별하고, 삭제 대상의 볼륨 ID·크기·AZ가 예상한 리소스와 일치하는지 확인한 뒤 수동으로 삭제합니다.

```powershell
kubectl -n fitzza get pvc qdrant-storage-qdrant-0 -o wide
$pv = kubectl -n fitzza get pvc qdrant-storage-qdrant-0 -o jsonpath='{.spec.volumeName}'
kubectl get pv $pv -o jsonpath='{.spec.csi.volumeHandle}{"\n"}'
aws ec2 describe-volumes --volume-ids <volume-id> --query 'Volumes[0].{State:State,Size:Size,AZ:AvailabilityZone,Encrypted:Encrypted,Tags:Tags}'
```

백업과 대상 볼륨을 다시 확인한 후에만 PV와 EBS 볼륨을 수동 삭제합니다. 다른 워크로드가 사용 중인 볼륨이나 확인되지 않은 볼륨은 삭제하지 않습니다.

## AI 코드 경계

FashionCLIP/Jev Python 코드는 `fashion-CLIP` 저장소에서 이미지로 빌드해 commit SHA로 ECR에 올립니다. 이 저장소는 Qdrant 배포와 데이터 계약만 소유합니다. 임베딩 Job은 Qdrant와 동시에 큰 메모리를 사용하지 않도록 결과를 S3에 먼저 기록하고, 경량 importer가 `fitzza_products_current` 대상 버전 컬렉션에 적재합니다.

Qdrant API 키와 TLS는 인증서 및 키 교체 절차가 함께 준비될 때 활성화합니다. 그 전까지는 내부 전용 Service와 NetworkPolicy를 보안 경계로 사용합니다.
