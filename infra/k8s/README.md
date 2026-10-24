# Fitzza EKS deployment

This directory contains the local, credential-free Kubernetes deployment baseline.

## Prerequisites

- An EKS cluster with the AWS Load Balancer Controller installed
- ECR repositories for every application image, with tag immutability enabled
- An RDS PostgreSQL endpoint reachable from the private subnets
- An IAM association for the `fitzza-application` service account using EKS Pod Identity or IRSA
- A Kubernetes Secret named `fitzza-app-secrets`, populated from the approved secret store. The SSM transition is tracked in FITZZA-251; the existing RDS password still uses Secrets Manager until that transition is verified.

Do not apply `base/secret.example.yaml`. It documents required keys only and is intentionally excluded from Kustomize.

Production VTON uses the operator-managed `fitzza-prod-vton-runtime` Pod Identity role on
`fitzza/fitzza-application`. Scope that role to object read/write/delete on
`fitzza-prod-assets-vton` and send/receive/delete/change-visibility on `vton-jobs`.
The foundation S3 Gateway Endpoint separately admits that role only to the VTON asset
bucket. Keep `VTON_STORAGE_BACKEND=local` and `VTON_QUEUE_BACKEND=memory` until the
association and endpoint access are verified; then switch both values together.

Use `python scripts/validate_app_secrets.py` with JSON on stdin to validate all 13 keys without printing values or contacting AWS. The optional `--emit-manifest` writes sensitive JSON for direct piping to kubectl only. See the [pilot deployment runbook](../aws/cloudformation/PILOT_DEPLOYMENT.md) for the SSM transition, operating restrictions, and validation order.

After changing `fitzza-app-secrets`, restart every consuming Pod because environment
variables sourced with `envFrom` are captured only when a Pod starts. In particular,
restart and wait for both `vton-service` and `vton-worker`; verify only the presence of
the `OPENAI_API_KEY` variable and never print its value.

## Values to replace

Before deployment, replace the following placeholders through an environment-specific overlay or pipeline step:

- `CHANGE_ME_RDS_ENDPOINT`
- `CHANGE_ME_FRONTEND_ORIGIN`
- `CHANGE_ME_ACM_CERTIFICATE_ARN`
- `CHANGE_ME_ALB_SECURITY_GROUP_ID` (CloudFormation output `AlbSecurityGroupId`)
- `CHANGE_ME_API_DOMAIN`
- `CHANGE_ME_REFRESH_COOKIE_SECURE` (set by `scripts/render_production_manifests.py`: `true` with TLS, `false` without)

The production overlay contains image mappings for all 11 application services. CodeBuild's `post_build` step fills `CHANGE_ME_ECR_REGISTRY`, `CHANGE_ME_ECR_REPOSITORY_PREFIX`, and `CHANGE_ME_COMMIT_TAG` from `image-definitions.json`, using the same ECR paths and 12-character Git commit tag as the image build. CodeBuild requires a resolved Git commit SHA; there is no `local` tag fallback.

Deploy the production overlay from that build's artifact, which includes the populated mappings. When preparing an overlay manually, replace these three image placeholders with the registry (for example, `123456789012.dkr.ecr.ap-northeast-2.amazonaws.com`), repository prefix (default `fitzza`), and commit tag of the images actually pushed to ECR before rendering or applying it.

## Local validation

```powershell
kubectl kustomize infra/k8s/overlays/prod
```

## Deployment order

The production overlay explicitly sets `SPRING_PROFILES_ACTIVE=native,prod` for Config Server. Its classpath configuration backend requires `native`; the shared ConfigMap's `prod` profile alone would disable that backend. Other services retain the shared `prod` profile.

Production Java Config clients override `SPRING_CONFIG_IMPORT` with a required `configserver:http://config-service:8888` import. They fail startup if configuration is unavailable instead of silently continuing with local defaults. Local application YAML keeps its optional import.

CodeBuild runs `scripts/deploy_eks.py`: apply non-application resources, apply Config Server/Discovery, wait for Config Server/Discovery/Redis/Qdrant rollouts, then apply the full manifests and wait for the nine remaining applications. A prerequisite failure stops before the application apply; it does not automatically undo resources already applied. The script contacts the active Kubernetes context and must only run during the approved operating window.

1. Create the namespace and synchronized secret.
2. Deploy Redis, Config Server, and Discovery Service.
3. Deploy domain services and Python services.
4. Deploy Gateway and the ALB Ingress.
5. Verify every `/health` endpoint before routing production traffic.

The ALB uses the dedicated CloudFormation security group and lets AWS Load Balancer Controller manage only the backend rule required for pod targets. RDS must use the `RdsSecurityGroupId` output. The current Redis is a private `ClusterIP` service inside EKS; use `ManagedRedisSecurityGroupId` only if it is later replaced with ElastiCache or another VPC-managed Redis service.

Qdrant deployment, collection, persistence, and snapshot recovery procedures are documented in [QDRANT.md](QDRANT.md).

## Redis updates

The Redis PVC explicitly uses the existing `fitzza-gp3-retain` StorageClass. The cluster has no default StorageClass, so omitting it leaves a new PVC pending. Applying the Redis manifest provisions a separate 5 GiB EBS volume; this local configuration change does not create one. The class retains volumes after PVC deletion, so review retained Redis volumes during teardown.

This manifest assumes an existing `redis-data` PVC was already bound with `fitzza-gp3-retain`; a bound PVC's `storageClassName` cannot be changed in place. Before applying `base/redis.yaml` to an existing cluster, confirm that `kubectl -n fitzza get pvc redis-data -o jsonpath='{.spec.storageClassName}'` prints `fitzza-gp3-retain`. If it prints another class, do not apply the PVC: moving Redis data to this class requires a backup, PVC recreation and restore, which this baseline does not cover. CD never applies this PVC because it is operator-owned.

Redis uses one replica with a `Recreate` update strategy and a shared `ReadWriteOnce` data volume. During an update, the existing Pod terminates before its replacement starts, so Redis is unavailable until the replacement is ready. Schedule Redis updates in a maintenance window and account for failures in Redis-dependent requests during this interruption.

After applying the update, wait for `kubectl -n fitzza rollout status deployment/redis --timeout=300s` to succeed and verify the application health endpoints before routing production traffic again.
