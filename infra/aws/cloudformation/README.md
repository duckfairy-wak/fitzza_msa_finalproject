# Fitzza AWS foundation

This directory provisions the first deployable AWS baseline for the approved Fitzza project budget.

## Included resources

- A dedicated VPC across two Availability Zones in `ap-northeast-2`
- Two public and two private subnets
- One public NAT Gateway and one Elastic IP
- An S3 Gateway VPC Endpoint for pipeline traffic and ECR image-layer downloads without NAT processing
- Dedicated security groups for the public ALB and private RDS/managed Redis access
- One private, encrypted PostgreSQL 17.6 `db.t4g.micro` instance with a Secrets Manager-managed master password
- One EKS 1.36 Standard cluster
- One ARM64 `t4g.large` managed node group with `min=0`, `desired=0`, `max=1` for pilot workload capacity; the size increase was approved on 2026-10-21 while the usage plan is being revised.
- The sole worker uses the AZ-c private subnet so the retained Qdrant EBS volume remains attachable when scaled to one node.
- EventBridge Scheduler and Lambda automation for weekday 09:00 scale-up and 18:00 scale-down (`Asia/Seoul`), with scale-up blocked on weekends and configured exclusion dates
- Approved exception: 2026-10-24 through 2026-10-26, each day 12:00 start / 23:00 scale-down request KST. Six one-time schedules call only the existing node scaler; no crawler Job or service-maintenance automation is installed.
- EKS managed add-ons for VPC CNI, CoreDNS, kube-proxy, Pod Identity, and EBS CSI
- An EKS Pod Identity role for AWS Load Balancer Controller v3.6.0
- A private, encrypted, versioned S3 bucket for crawler and AI pipeline data
- A CloudFront OAC distribution that can read only `public/product-images/*` from that private bucket
- Immutable ECR repositories for the 11 services, Crawler, and FashionCLIP

The single NAT Gateway is a temporary cost decision for this project. It is a single-AZ outbound dependency and must be reconsidered before production use.

### Approved crawler operating-window exception

`scripts/configure_approved_crawler_window.py` defaults to no AWS calls. An explicitly approved
`--apply-approved-window --backup <new-directory>` operation checks the live Lambda source against the
reviewed baseline, backs up its package and both weekday schedules, then applies only its code and six
one-time Scheduler entries. It preserves all weekday schedule options and the existing execution role.
Shutdowns are installed before starts. A partial API failure must be inspected; do not blindly rerun.

The 10/26 09:00 request is rejected by the date/time guard. The existing weekday 18:00 payload carries
`scheduledWeekdayShutdown=true` so it is skipped during this exception only. Manual `desiredSize=0`
remains usable at any time. Weekend/blocked-date exclusions resume after 10/26 with no follow-up automation.
The six exception schedules self-delete after execution. Node count/size, IAM roles, app replicas, CD and
all crawler/AI Job suspend flags remain unchanged. Startup and termination take additional time;
23:00 is a scale-down request, not proof that EC2 billing has stopped. Finish data work/checkpoints earlier.

This narrow service-API patch intentionally creates Lambda code drift until the foundation template is
next deployed through normal review; do not deploy the whole foundation just to change these hours.
Future foundation deployment must retain the exception guard while these dates are in effect. If the
template exceeds 51,200 bytes, use S3 template upload/`--template-url` rather than inline `--template-body`.

The ALB itself is created from `infra/k8s/base/ingress.yaml` by AWS Load Balancer Controller. Replace `CHANGE_ME_ALB_SECURITY_GROUP_ID` with the stack output `AlbSecurityGroupId`. The controller manages the matching backend rule for pod targets; do not attach the public ALB security group to EKS nodes or data stores.

RDS is deployed in the private subnets with `PubliclyAccessible=false`. Use the stack outputs `RdsEndpointAddress` and `RdsMasterSecretArn` when preparing the production Kubernetes Secret. The current Redis deployment is exposed only as a Kubernetes `ClusterIP`; `ManagedRedisSecurityGroupId` is reserved for a future managed Redis migration.

## Install the AWS Load Balancer Controller

The foundation stack creates the IAM policy, Pod Identity role, and association for service account `kube-system/aws-load-balancer-controller`. Install the pinned controller only after the stack update completes. Pass the region and VPC explicitly so the Pod never needs EC2 instance metadata.

```powershell
helm repo add eks https://aws.github.io/eks-charts
helm repo update eks
helm upgrade --install aws-load-balancer-controller eks/aws-load-balancer-controller `
  --namespace kube-system `
  --version 3.6.0 `
  --set clusterName=fitzza-prod `
  --set region=ap-northeast-2 `
  --set vpcId=<VpcId stack output> `
  --set serviceAccount.create=true `
  --set serviceAccount.name=aws-load-balancer-controller

kubectl -n kube-system rollout status deployment/aws-load-balancer-controller --timeout=300s
kubectl get ingressclass alb
```

## Delivery pipeline

`delivery.yaml` creates a GitHub connection, a CodePipeline V2 pipeline, and one CodeBuild project. A push to `main` runs:

1. **Source**: the exact pushed commit through the GitHub App connection. The commit SHA is passed to CodeBuild as `SOURCE_COMMIT_ID`.
2. **Build** (`buildspec.yml`): Gradle tests, both FastAPI test suites, and the root script tests run first. Only after they all pass does CodeBuild log in to ECR and run `scripts/publish_images.sh`, which publishes native `linux/arm64` images tagged with the 12-character commit SHA and checks each image's architecture.
3. **Deploy**: disabled by default (`EnableDeployStage=false`). Enable it once RDS, the `fitzza-app-secrets` Kubernetes Secret, and the AWS Load Balancer Controller are ready.

A failed test aborts the build phase, so no image is pushed and no later stage runs.

### Budget guardrails

CodeBuild, CodePipeline, and KMS are not line items in the approved estimate, so the pipeline is sized to stay at or near zero:

- ARM `BUILD_GENERAL1_SMALL` (`arm1.small`) builds natively on Graviton without QEMU and is covered by the CodeBuild free tier of 100 build minutes per month.
- A service whose image inputs did not change is retagged in ECR (`src-<content hash>` → commit tag) instead of rebuilt. Only changed services consume build minutes and ECR storage.
- `SUPERSEDED` execution mode runs only the newest of several queued pushes. Builds are limited to one at a time and 60 minutes.
- No customer-managed KMS key: artifacts use S3 default encryption and expire after 14 days. Build logs are kept for 7 days.
- ECR keeps the latest three images per repository (foundation stack lifecycle policy), which stays within the 5 GB estimate and still allows rollback.
- Base images come from the ECR Public mirror of Docker Official Images to avoid anonymous Docker Hub pull limits on shared CodeBuild addresses.

### Deploy the build pipeline

The defaults deploy the Source and Build stages only. Review the change set before executing it.

```powershell
aws cloudformation deploy `
  --stack-name fitzza-prod-delivery `
  --template-file infra/aws/cloudformation/delivery.yaml `
  --capabilities CAPABILITY_IAM `
  --tags Project=fitzza Environment=prod Owner=team3 CostCenter=lgcns5-retail `
  --no-execute-changeset `
  --profile fitzza `
  --region ap-northeast-2
```

The connection created by CloudFormation remains `PENDING` until the repository owner completes the GitHub authorization in AWS Console → Developer Tools → Settings → Connections. Limit the GitHub App installation to `duckfairy-wak/fitzza_msa_finalproject`. The pipeline cannot fetch source until the connection is `AVAILABLE`, so the automatic run at pipeline creation fails at Source without starting CodeBuild.

### Verify a build

Run the pipeline for a specific commit, then confirm the images:

```powershell
aws codepipeline start-pipeline-execution `
  --name fitzza-prod-delivery `
  --source-revisions actionName=Source,revisionType=COMMIT_ID,revisionValue=<full commit SHA> `
  --profile fitzza `
  --region ap-northeast-2

aws ecr describe-images `
  --repository-name fitzza/gateway-service `
  --image-ids imageTag=<first 12 characters of the SHA> `
  --profile fitzza `
  --region ap-northeast-2
```

The build artifact `image-publish-report.json` lists, for every service, whether the image was built, retagged, or already present, with its digest and architecture.

### Enable the deploy stage

The production overlay allows up to 600 seconds for application startup because concurrent Java cold starts on the single pilot worker exceeded the base 120-second window. Readiness and liveness checks remain unchanged; a startup timeout is still a deployment failure. Application Deployments set `progressDeadlineSeconds: 900`, and `scripts/deploy_eks.py` waits up to 900 seconds per rollout, so image pull and scheduling time on top of a full startup window does not end the rollout early.

Application updates use `maxSurge=0`, `maxUnavailable=1` because the single worker has no CPU request headroom for extra application Pods. Each service can be unavailable during replacement; this pilot configuration is not zero-downtime or highly available.

Follow [the pilot deployment runbook](PILOT_DEPLOYMENT.md) for the Secret budget correction and the 10/20 validation sequence before the 10/21 pilot.

Before enabling CD, an operator must provision the namespace, application Secret, service account, Redis/PVC, Qdrant/PVC, StorageClass and Qdrant NetworkPolicy, then apply `infra/k8s/bootstrap/delivery-rbac.yaml`. These operator-owned resources are excluded from `infra/k8s/overlays/delivery`; in particular CD never reapplies Qdrant's immutable volume claim template.

Set foundation parameter `DeliveryArtifactBucketName` to the delivery stack's `ArtifactBucketName` output. The S3 Gateway Endpoint otherwise allows only project data and ECR layers, so the VPC deploy worker cannot download or upload pipeline artifacts. This optional rule permits only that exact bucket for principals in this account; IAM must separately authorize each action.

The deploy access entry maps only to Kubernetes group `fitzza-delivery`, bound to a Role in namespace `fitzza`. It cannot read Secrets, mutate PVCs/StatefulSets, create RBAC or manage cluster resources. The role can modify application workloads, which inherently use the pre-provisioned application credentials; do not attach privileged workload service accounts in this namespace.

Resolve the foundation outputs and the EKS cluster security group, fill `delivery-parameters.example.json` into a local `delivery-parameters.json`, and redeploy with `EnableDeployStage=true`. The template rejects the update if any deploy input is missing. TLS is optional only for initial ALB reachability testing; for a production endpoint pass both `ApiDomain` and `AcmCertificateArn`. The renderer sets `REFRESH_COOKIE_SECURE` to `true` only when both TLS values are supplied and to `false` for HTTP-only reachability tests, because browsers drop Secure cookies over plain HTTP. Deploy preflight checks existing PVCs and Qdrant without reading Secret contents; a missing application Secret fails Pod startup and therefore rollout.

### Rollback

Images are immutable and tagged with the 12-character Git commit SHA. For a failed application update, an authorized operator can inspect `kubectl -n fitzza rollout history deployment/<service>` and run `kubectl -n fitzza rollout undo deployment/<service> --to-revision=<verified-good-revision>`. Confirm the restored image, rollout, external health and relevant API before restoring traffic. Preserve known-good image digests before a release; ECR retention does not guarantee an old tag still exists.

For emergency image-only recovery, an operator may run `kubectl -n fitzza set image deployment/<service> <container>=<verified-good-image>` or a full `rollout undo`. Both are update operations: even with `--field-manager=fitzza-codebuild`, the API server records the image field under a separate `fitzza-codebuild`/`Update` owner (`kubectl-rollout` for undo). The next CD apply with a different image then fails with an image-field conflict. Before resuming CD, remove that update owner from the recovered Deployment. This removes ownership records only: field values stay and Pods do not restart. Remove the whole entry even when it also owns other template fields (for example after `rollout undo`), so that CD becomes the only owner of every field it applies; removing only the image path would leave later conflicts on those fields. The block patches only when exactly one main-resource `apps/v1` Update entry owns the image, and the patch is rejected if the Deployment or that entry changed after the listing:

```powershell
$svc = "<service>"
$deploy = kubectl -n fitzza get deployment $svc --show-managed-fields -o json | ConvertFrom-Json
$mf = @($deploy.metadata.managedFields)
$owners = 0..($mf.Count - 1) | ForEach-Object { [pscustomobject]@{ index = $_; manager = $mf[$_].manager; operation = $mf[$_].operation; apiVersion = $mf[$_].apiVersion; subresource = $mf[$_].subresource; ownsImage = (($mf[$_].fieldsV1 | ConvertTo-Json -Depth 50 -Compress) -match '"f:image"') } }
$owners | Format-Table -AutoSize
$target = @($owners | Where-Object { $_.operation -eq "Update" -and $_.ownsImage -and $_.apiVersion -eq "apps/v1" -and -not $_.subresource })
if ($target.Count -eq 1) {
  $i = $target[0].index
  $patch = @(
    @{ op = "test"; path = "/metadata/resourceVersion"; value = $deploy.metadata.resourceVersion },
    @{ op = "test"; path = "/metadata/managedFields/$i/manager"; value = $target[0].manager },
    @{ op = "test"; path = "/metadata/managedFields/$i/operation"; value = "Update" },
    @{ op = "test"; path = "/metadata/managedFields/$i/apiVersion"; value = "apps/v1" },
    @{ op = "remove"; path = "/metadata/managedFields/$i" }
  )
  ConvertTo-Json -InputObject $patch -Compress | Set-Content -Path "$env:TEMP\managedfields-patch.json" -Encoding ascii
  kubectl -n fitzza patch deployment $svc --type=json --patch-file "$env:TEMP\managedfields-patch.json"
} elseif ($target.Count -eq 0) {
  Write-Host "No Update owner of the image remains."
} else {
  Write-Warning "Several Update entries own the image; inspect them before patching."
}
```

Run the block again; it should report that no Update owner of the image remains and list `fitzza-codebuild`/`Apply` as the image owner. If a Deploy already failed on this conflict, retry only that action:

```powershell
$id, $status, $revision = (aws codepipeline list-pipeline-executions --pipeline-name fitzza-prod-delivery --max-results 1 --profile fitzza --region ap-northeast-2 --query "pipelineExecutionSummaries[0].[pipelineExecutionId,status,sourceRevisions[0].revisionId]" --output text) -split "\s+"
"$id $status $revision"
if ($status -eq "Failed") {
  aws codepipeline retry-stage-execution --pipeline-name fitzza-prod-delivery --stage-name Deploy --pipeline-execution-id $id --retry-mode FAILED_ACTIONS --profile fitzza --region ap-northeast-2
} else {
  Write-Warning "The latest execution is $status; never retry an older run over a newer deployment."
}
```

Confirm that the printed revision is the one you intend to deploy. Do not use `set image --field-manager=fitzza-codebuild` to hand ownership back. Never resolve this by forcing conflicts on all resources or on Qdrant storage; a forced apply of a partial manifest also removes fields that only CD owned.

### Pilot evidence (2026-10-21)

- Pipeline execution `a33f217f-ea25-4d12-a101-832f8c346079`: Source/Build/Deploy succeeded for source `c4fd7ddc34996846b1d1d80d5bed58c7ca51aed8`; successful deploy build `76f70d28-4dcc-4c09-a502-a9d12f791fa8`.
- Initial deploy retries exposed an artifact endpoint denial and the manual rollback image ownership conflict; both were corrected without cluster-admin access or forcing storage fields. The successful BuildOutput was reused for deploy retries.
- All 11 application images use tag `c4fd7ddc3499`; Redis and Qdrant remain operator-owned. External health and product read returned HTTP 200; API CORS accepted the configured localhost origin.
- Gateway invalid-image injection produced ErrImagePull and external HTTP 503. Restoring the verified revision recovered HTTP 200. Qdrant PVC identity and collection/point counts (2/2) were unchanged before/after recovery and CD.
- This verifies a manually triggered exact-commit pipeline and Gateway image recovery, not database migration rollback or automatic failure recovery.
- Develop integration: PR #138 merged as `c850ab334ea32e7c6150b1a158b9e8c788c7b95e`. That push did not start an execution, so it was run manually (`1d229338-b7a3-4925-befb-253aaa53c44f`). Its first deploy (`4aed51e0-0be5-46a9-8cf9-a11ac9fda31c`) failed on the Gateway image field still owned by `fitzza-codebuild`/`Update` from the earlier `set image`; removing only that owner and retrying the Deploy action succeeded (`8d945ac2-4c88-4186-9bed-296a584fcd37`).
- The next develop push, `cfabd98f41413b0a65e7ad864e0eb2bf8718f0db`, started execution `dfded4ff-0be3-4e01-b262-a27058e7ec2c` through the `WebhookV2` trigger and succeeded end to end. All 11 images use `cfabd98f4141`, the Qdrant PVC identity is unchanged, and external health, product read and API CORS checks passed.

Do not rerun an old source revision whose deployspec predates the namespace-only delivery overlay: that older deployment contract may require prohibited cluster permissions. Use the current reviewed deployment tooling with known-good images instead. Rolling back an image does not reverse database migrations, Secret rotation or data changes. No automatic rollback is configured; a failed deployment stops the pipeline and requires this explicit recovery procedure.

## Cost controls

- Deploy only in `ap-northeast-2`, which is the approved estimate region.
- The node group starts at zero. Scale it to one only during the approved operating window.
- Scale-up is blocked on weekends and on the `NodeScaleUpBlockedDates` dates. The default exclusions are `2026-10-19` and `2026-10-26` in `Asia/Seoul`.
- The EKS control plane and NAT Gateway charge continuously while the stack exists.
- The S3 Gateway Endpoint avoids NAT processing charges for S3 traffic.
- Delete the stack after the project, then manually review retained S3 data.
- Mirrored product images add S3 storage and request charges plus CloudFront request and data-transfer
  charges. `PriceClass_100` limits edge locations, while content-addressed object keys and immutable
  caching reduce repeat origin reads. Review the current S3 and CloudFront pricing before deployment.

## Product image audit and migration

The product API currently returns externally hosted image URLs. Some source-CDN objects return `404`
when the browser sends the `https://app.fitzza.site/` referrer even though a direct request succeeds.
Run the migration in three reviewed phases. The commands below write reports locally; only the mirror
command with its explicit flag writes to S3, and no command connects to PostgreSQL.

1. Audit all representative, detail, option, size-guide, and color-mapping image references:

   ```powershell
   python scripts/migrate_product_images.py audit `
     --output artifacts/product-image-audit.json
   ```

2. Deploy the reviewed foundation change. Record the `DataBucketName` and `ProductImageBaseUrl`
   outputs. Keep Block Public Access enabled; CloudFront OAC is allowed to read only the image prefix.

3. Mirror verified image bytes. The script checks the AWS account, validates image media type and
   signature, uses content-addressed immutable keys, refuses conflicting objects, and reads metadata
   back after upload:

   ```powershell
   python scripts/migrate_product_images.py mirror `
     --manifest artifacts/product-image-audit.json `
     --output artifacts/product-image-mapping.json `
     --sql-output artifacts/product-image-migration.sql `
     --account-id <AWS_ACCOUNT_ID> `
     --bucket <DataBucketName> `
     --public-base-url <ProductImageBaseUrl> `
     --apply-s3-writes
   ```

The generated SQL starts a transaction but ends with `ROLLBACK`. Execute it against a maintenance or
staging copy first, inspect affected row counts and sample CloudFront URLs, and replace the final line
with `COMMIT` only for the reviewed production run. Each update includes the product/option/sequence
identity and the expected old URL, so a concurrently changed row is not overwritten.

Keep frontend `referrerPolicy="no-referrer"` and an image fallback until the migration is complete.
Before production operation, enable encrypted CloudTrail S3 data events for the image prefix, review
CloudFront standard metrics and alarms, and choose an access-logging destination with its own retention
and encryption policy. These observability features can add request, ingestion, and storage charges.
- ECR repositories use `EmptyOnDelete` so stack deletion can remove build images.
- The data bucket is retained on stack deletion to prevent accidental data loss.

## Validate

Use a real public `/32` address only for deployment. The address in `parameters.example.json` is documentation-only.

```powershell
aws cloudformation validate-template `
  --template-body file://infra/aws/cloudformation/foundation.yaml `
  --profile fitzza `
  --region ap-northeast-2
```

## Preview and deploy

First obtain the current operator public IPv4 address and append `/32`. Do not use `0.0.0.0/0`.

```powershell
$operatorCidr = "203.0.113.10/32"

aws cloudformation deploy `
  --stack-name fitzza-prod-foundation `
  --template-file infra/aws/cloudformation/foundation.yaml `
  --capabilities CAPABILITY_IAM CAPABILITY_AUTO_EXPAND `
  --parameter-overrides `
    ProjectName=fitzza `
    Environment=prod `
    Owner=team3 `
    CostCenter=lgcns5-retail `
    KubernetesVersion=1.36 `
    NodeScaleUpBlockedDates=2026-10-19,2026-10-26 `
    ClusterPublicAccessCidrs=$operatorCidr `
  --tags Project=fitzza Environment=prod Owner=team3 CostCenter=lgcns5-retail `
  --no-execute-changeset `
  --profile fitzza `
  --region ap-northeast-2
```

Review the generated change set in CloudFormation. Execute it only after confirming that it creates one EKS control plane, one NAT Gateway, one Elastic IP, and one scale-to-zero node group.

```powershell
aws cloudformation execute-change-set `
  --stack-name fitzza-prod-foundation `
  --change-set-name <generated-change-set-name> `
  --profile fitzza `
  --region ap-northeast-2
```

After stack completion:

```powershell
aws eks update-kubeconfig `
  --name fitzza-prod `
  --profile fitzza `
  --region ap-northeast-2

aws eks update-nodegroup-config `
  --cluster-name fitzza-prod `
  --nodegroup-name fitzza-prod-arm64-c-large `
  --scaling-config minSize=0,maxSize=1,desiredSize=1 `
  --profile fitzza `
  --region ap-northeast-2
```

Return `desiredSize` to zero after the approved work window.

## Verify scheduled scaling

The schedules invoke a least-privilege Lambda that accepts only `desiredSize` 0 or 1. Scale-up requests are skipped on `Asia/Seoul` weekends and on dates configured by `NodeScaleUpBlockedDates`; scale-down remains allowed every day. Test scale-up during the approved work window:

```powershell
aws lambda invoke `
  --function-name fitzza-prod-node-scaler `
  --payload '{"desiredSize":1}' `
  --cli-binary-format raw-in-base64-out `
  --profile fitzza `
  --region ap-northeast-2 `
  node-scaler-result.json

aws eks describe-nodegroup `
  --cluster-name fitzza-prod `
  --nodegroup-name fitzza-prod-arm64-c-large `
  --query 'nodegroup.scalingConfig' `
  --profile fitzza `
  --region ap-northeast-2
```

After verifying that one node becomes `Ready`, invoke the function with `{"desiredSize":0}` or wait for the weekday 18:00 schedule. Never leave the node running outside the approved window.

## Teardown

Stack deletion stops EKS, EC2, NAT Gateway, Elastic IP, and other stack-managed charges. The data bucket is intentionally retained and must be reviewed separately.

```powershell
aws cloudformation delete-stack `
  --stack-name fitzza-prod-foundation `
  --profile fitzza `
  --region ap-northeast-2
```

After deletion completes, verify that no NAT Gateway, Elastic IP, EKS cluster, load balancer, RDS instance, or EBS volume remains.
