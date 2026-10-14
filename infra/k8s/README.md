# Fitzza EKS deployment

This directory contains the local, credential-free Kubernetes deployment baseline.

## Prerequisites

- An EKS cluster with the AWS Load Balancer Controller installed
- ECR repositories for every application image, with tag immutability enabled
- An RDS PostgreSQL endpoint reachable from the private subnets
- An IAM association for the `fitzza-application` service account using EKS Pod Identity or IRSA
- A Kubernetes Secret named `fitzza-app-secrets`, populated from AWS Secrets Manager in the deployed environment

Do not apply `base/secret.example.yaml`. It documents required keys only and is intentionally excluded from Kustomize.

## Values to replace

Before deployment, replace the following placeholders through an environment-specific overlay or pipeline step:

- `CHANGE_ME_RDS_ENDPOINT`
- `CHANGE_ME_FRONTEND_ORIGIN`
- `CHANGE_ME_ACM_CERTIFICATE_ARN`
- `CHANGE_ME_API_DOMAIN`

The production overlay contains image mappings for all 11 application services. CodeBuild's `post_build` step fills `CHANGE_ME_ECR_REGISTRY`, `CHANGE_ME_ECR_REPOSITORY_PREFIX`, and `CHANGE_ME_COMMIT_TAG` from `image-definitions.json`, using the same ECR paths and 12-character Git commit tag as the image build. CodeBuild requires a resolved Git commit SHA; there is no `local` tag fallback.

CodeBuild checks each service's ECR tag and reuses existing images when rebuilding the same commit. Only missing tags are built and pushed; lookup errors stop the build. The CodeBuild role needs `ecr:DescribeImages` permission for these repositories.

Deploy the production overlay from that build's artifact, which includes the populated mappings. When preparing an overlay manually, replace these three image placeholders with the registry (for example, `123456789012.dkr.ecr.ap-northeast-2.amazonaws.com`), repository prefix (default `fitzza`), and commit tag of the images actually pushed to ECR before rendering or applying it.

## Local validation

```powershell
kubectl kustomize infra/k8s/overlays/prod
```

## Deployment order

1. Create the namespace and synchronized secret.
2. Deploy Redis, Config Server, and Discovery Service.
3. Deploy domain services and Python services.
4. Deploy Gateway and the ALB Ingress.
5. Verify every `/health` endpoint before routing production traffic.

## Redis updates

Redis uses one replica with a `Recreate` update strategy and a shared `ReadWriteOnce` data volume. During an update, the existing Pod terminates before its replacement starts, so Redis is unavailable until the replacement is ready. Schedule Redis updates in a maintenance window and account for failures in Redis-dependent requests during this interruption.

After applying the update, wait for `kubectl -n fitzza rollout status deployment/redis --timeout=300s` to succeed and verify the application health endpoints before routing production traffic again.
