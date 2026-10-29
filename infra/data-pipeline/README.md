# Crawler to Jev contract

## Review import report

For an existing run, create `reviews/report.json` without changing review JSON:

```powershell
python -m src.review_report `
  --bucket fitzza-prod-foundation-databucket-wwng6wfc0hqy `
  --prefix pipeline/runs/collection-20261025-01
```

## Full AWS collection with image files

`crawler-full-run-job.yaml` runs the manually approved 3,000-product collection
entirely on EKS. It restores product-screening checkpoints, combines qualified
seed and new products, and streams product images, privacy-minimized reviews and
review images directly to the run-specific S3 prefix. The Job does not invoke Jev,
embeddings or Qdrant indexing.

The 2026-10-25 run uses:

```text
s3://fitzza-prod-foundation-databucket-wwng6wfc0hqy/pipeline/runs/collection-20261025-01/
status.json
crawler/checkpoints.json
curated/data/<category>/<product-id>.json
curated/manifest.json
images/products/<product-id>/
reviews/data/<product-id>.json
images/reviews/<product-id>/<review-id>/
```

The EKS Job has a 72-hour deadline and no retry. Candidate discovery starts with
the larger of 18x the category quota or 10,000 products, while completed categories
are skipped on checkpoint restore. Newer product IDs are screened first to avoid
spending the initial batches on stale listings. Screening uses eight concurrent direct
HTTP workers behind a shared request-rate gate. A server `Retry-After` response pauses
all workers so parallel requests do not extend a temporary block. It does not wait for browser rendering because the server response
already contains the validated `__NEXT_DATA__` contract. Recreating it with the same run ID
restores crawler checkpoints and skips completed media objects. Its Pod Identity is
limited to the exact run prefix. Inspect progress with `kubectl logs` or the S3
`status.json`; application deployments are not restored automatically.

Checkpoint restoration downloads and verifies 16 content-addressed S3 objects in
parallel and prints progress every 500 objects. SHA-256 verification still completes
before each restored file is written.

Apparel still requires centimeter actual-size measurements. Shoes and hats may
instead use the product's purchasable size options when Musinsa does not publish a
measurement table. Fallback provenance is retained in internal checkpoints only;
the curated product JSON keeps the existing external field set.

Shoe and hat image evidence uses explicit color-chip images first. When absent, one
declared color may use the product's primary image. An accessory with no color
dimension keeps the primary image under the existing non-empty `color_raw` contract;
products with multiple colors but no per-color images remain rejected.

Product image downloads isolate source-side failures such as HTTP 404, timeouts, and
invalid image payloads. Skipped URLs are written below the separate S3 `audit/`
prefix so the existing product and review JSON contracts do not change. Review images
are not downloaded. S3 upload and permission failures still stop the run.

Cloud deployment and execution are separate. See [DEPLOYMENT.md](DEPLOYMENT.md) for the suspended Jobs, approved bundle contract and masked SSM key registration. The examples below describe the earlier local workflow, not permission to run collection or indexing.

The prepared `src.cloud_curate` stage verifies seed/raw hashes, selects the 3000-product category/season quotas,
and creates Jev's `data/` bundle only when the input contract passes. It never guesses missing color-image mappings,
starts Jev, or grants human/indexing approval. It is suspended in EKS; actual collection remains separately authorized.

The AI data pipeline runs in this order:

```text
Crawler -> Jev color normalization -> FashionCLIP embedding -> Qdrant upsert
```

The FashionCLIP Jev implementation reads the crawler's product JSON directory directly. It uses:

- `name`
- `dataset.logical_category`
- every `color_image_mappings[].color_raw`
- all sibling colors on the same product

The cloud crawler now emits explicit COLOR_CHIP option/image relationships only when an active
option item confirms the same product and option value IDs. It preserves raw color names and
records option-ID evidence; it never falls back to product-name guesses, generic swatches, or
another product's image. This is metadata evidence, not image-content or human quality approval.
OtherColorGoods-only products remain unsupported pending an observed non-empty source fixture.

`scripts/validate_jev_data.py` validates the files before any paid Jev request. Color keys follow the Jev implementation's `strip().lower()` rule. It does not create an intermediate input file.

## Crawled product publication and import

Curated products for run `collection-20261025-01` live under
`s3://fitzza-prod-foundation-databucket-wwng6wfc0hqy/pipeline/runs/collection-20261025-01/`.
Backend product DB load (not reviews) uses:

```powershell
python -X utf8 scripts/download_curated_products.py --run-id collection-20261025-01
python -X utf8 scripts/render_crawled_product_import.py `
  --data .data/collection-20261025-01/curated/data `
  --status .data/collection-20261025-01/status.json `
  --manifest .data/collection-20261025-01/curated/manifest.json `
  --output .data/collection-20261025-01/product-import.sql
```

Execute the SQL with `product_service_app` from a short-lived private-network pod,
verify `count(*)` for `source='musinsa'`, then delete the pod and local SQL. See
[infra/seed/README.md](../seed/README.md#크롤링-상품-collection-20261025-01) and
[DB_IMPORT_GUIDE.md](DB_IMPORT_GUIDE.md). Reviews remain a separate import
(`render_crawled_review_import.py` / `review_service_app`).

After product rows exist, remap stored image values to S3 object keys with
`scripts/render_product_image_s3_key_update.py` when inventory manifests are available.
API responses resolve those keys to Presigned GET URLs in product-service.

## Crawled review publication and import

Review crawler output is stored under the immutable production prefix
`s3://fitzza-prod-foundation-databucket-wwng6wfc0hqy/pipeline/runs/<run-id>/reviews/`.
Keep the raw JSON private and encrypted. Upload `data/*.json` and `report.json`; do not
put the generated SQL in Git or S3 because it is only a short-lived deployment artifact.

After the release containing `V2__support_external_reviews.sql` has completed and the
`review-service` rollout is healthy, render the idempotent database import locally:

```powershell
python -X utf8 scripts/render_crawled_review_import.py `
  --input .data/review-crawl-500-20261022/data `
  --report .data/review-crawl-500-20261022/report.json `
  --output .data/review-crawl-500-20261022/import.sql `
  --skip-invalid
```

The renderer fails closed for incomplete crawler runs, duplicate source IDs, invalid
timestamps, blank or oversized content, and ratings outside 1 through 5. `--skip-invalid`
must be an explicit operator choice. The SQL runs in one transaction and upserts on
`(source, source_review_id)`, so retrying the same reviewed run does not create duplicates.
Execute it with the `review_service_app` database identity from a short-lived pod in the
private EKS network, verify the imported count and public API response, and then delete
both the pod and local SQL file. Never print database credentials or place them in the SQL.

For local Docker Compose QA, `scripts/load_local_reviews.py` validates the same crawler output
and streams the rendered SQL into the Compose `postgres` service without writing a file. It
cannot reach RDS. See [infra/seed/README.md](../seed/README.md#크롤링-리뷰-로컬-qa).

## Local usage

Use the crawler's qualified product `data/` directory, not candidate or audit output.

```powershell
python scripts/validate_jev_data.py `
  --source .data/color-qualified-dataset-500/data
```

After validation, run `fashion-CLIP/scripts/generate_color_map.py` with the same directory as `--data`. The implementation reference is the `feat/color-map-jev` branch; pin its reviewed commit before deployment because it is not merged into `main`.

## Jev API key on Windows

Do not paste the key into source files, Compose YAML, shell history, screenshots, or chat. In PowerShell, enter it as a masked value for the current terminal session:

```powershell
$secureKey = Read-Host "TYPESAFE_API_KEY" -AsSecureString
$keyPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureKey)
try {
  $env:TYPESAFE_API_KEY = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($keyPointer)
} finally {
  [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($keyPointer)
}
```

Confirm only whether it is set; never print the value:

```powershell
if ($env:TYPESAFE_API_KEY) { "TYPESAFE_API_KEY is set" } else { "TYPESAFE_API_KEY is missing" }
```

Run Jev from the repository root in the same terminal:

```powershell
python -X utf8 .data/fashion-clip/scripts/generate_color_map.py `
  --data .data/color-qualified-dataset-500/data `
  --config .data/fashion-clip/config `
  --workers 4
```

Remove the key when finished or close the terminal:

```powershell
Remove-Item Env:TYPESAFE_API_KEY
```

This session-only method is for local execution. The cloud deployment reads its key from SSM SecureString `/fitzza/prod/data-pipeline/typesafe-api-key` only after separate execution approval. Do not create a new Secrets Manager resource for this pipeline.

## Local FashionCLIP indexing

Run the batch from the local FashionCLIP checkout after `color_map.json` is generated. UTF-8 mode prevents Windows PowerShell's legacy console encoding from failing on Korean output or emoji.

```powershell
$env:PYTHONUTF8 = "1"
Push-Location .data/fashion-clip
.\.venv\Scripts\python.exe scripts\index_to_qdrant.py
Pop-Location
```

The current script recreates the local `musinsa_products` collection. Verify completion in the dashboard or with `GET http://localhost:6333/collections/musinsa_products`; `points_count` must be greater than zero.

## S3 run layout

Each execution uses an immutable run ID:

```text
runs/<run-id>/crawler/data/**/*.json
runs/<run-id>/crawler/report.json
runs/<run-id>/jev/color_map.json
runs/<run-id>/jev/color_map_review.csv
runs/<run-id>/jev/_SUCCESS.json
runs/<run-id>/fashion-clip/report.json
```

The layout above is historical. The deployed cloud contract uses `pipeline/runs/<run-id>/` and requires human color approval plus a separate matching dataset-quality approval; a Jev `_SUCCESS.json` alone is not sufficient. Jev credentials belong in SSM SecureString and must never be written to S3, Kubernetes manifests, or logs.

## Orchestration run contract (FITZZA-219)

Every automated run uses one immutable `run_id` and the input manifest SHA-256 as
its idempotency key. The machine-readable contract is
`run-contract.schema.json`; `run-contract.example.json` shows the expected shape.
The state machine must refuse to start a stage when its predecessor's success
marker is absent, and it must write a stage status document under
`pipeline/runs/<run-id>/status/`. Reusing a `run_id` with a different manifest
digest is invalid. A human approval remains required after Jev and before
FashionCLIP/Qdrant indexing.

The first state-machine definition is `orchestration.asl.json`. It invokes
small Lambda adapters so provider-specific EKS Job details stay outside the
workflow. Deploy-time substitutions must provide
`InitializeRunLambdaArn`, `CrawlerRunnerLambdaArn`, `ValidateImportLambdaArn`,
`JevRunnerLambdaArn`, `ReviewRequestLambdaArn`, `FashionClipRunnerLambdaArn`,
and `StatusWriterLambdaArn`. No credentials or secrets are stored in the
definition.

The deployable wrapper is `infra/aws/cloudformation/orchestration.yaml`. Upload
the ASL file to a versioned private S3 bucket, deploy this stack with the seven
adapter Lambda ARNs, and keep `ScheduleState=DISABLED` until the adapters and
run contract are deployed. The incremental rule defaults to Tuesday and
Thursday 10:00 Asia/Seoul (`cron(0 1 ? * TUE,THU *)`; EventBridge rule cron is
UTC) with `{"run_mode":"incremental"}`. It reads the approved current baseline manifest
and incremental checkpoint, so the crawler must submit only new or changed product
IDs; it must not rebuild the existing 3,000-product set. The integrity rule
defaults to Monday 11:00 Asia/Seoul (`cron(0 2 ? * MON *)`) with
`{"run_mode":"integrity"}` and is routed directly to the
validation adapter: it checks stored product data, image accessibility, and index
state without recrawling the catalog. A `full` run is manual-only and requires
`manual_approved: true`; use it only after a data-quality incident, site structure
change, or planned bulk refresh. Manual executions can start the state machine
directly with the same contract JSON. The template grants the state machine only
Lambda invocation and grants EventBridge only `states:StartExecution`.

The orchestration stack also grants the shared runner Lambda role
`eks:DescribeCluster` and associates the AWS-managed `AmazonEKSEditPolicy` only
to the configured `fitzza` namespace. The Lambda must have network access to
the EKS API endpoint; if the cluster endpoint is private, deploy the runner
functions into the foundation VPC subnets and security group. Public endpoint
CIDRs must include the runner's egress path.

`infra/aws/orchestration/job_spec.py` renders the Crawler and FashionCLIP Job
specifications used by the runner adapters. Each Job receives the run contract,
has CPU/memory requests and limits, and uses a deterministic name to prevent
duplicate execution. Jobs are placed like the other pipeline Jobs
(`kubernetes.io/arch: arm64`); set `PIPELINE_NODE_SELECTOR_JSON` on a runner to
target a dedicated pipeline node once one exists.

`infra/aws/orchestration/job_runner.py` provides the idempotent runner logic:
it reuses an existing Job for the same run and surfaces failure without creating
a duplicate. A Lambda invocation cannot outlive a pipeline Job, so the runner
waits at most `PIPELINE_JOB_WAIT_SECONDS` (default 600; keep the Lambda timeout
above it) and returns `job_status` `RUNNING` or `PENDING`. The state machine then
waits five minutes and calls the runner again until `SUCCEEDED`. The Job's
`activeDeadlineSeconds` (6 hours) bounds the total run.

The node runs only on weekdays 09:00-18:00 Asia/Seoul, so runners create a new
Job only inside `PIPELINE_RUN_WINDOW` (default `MON-FRI 09:30-16:00`, Asia/Seoul).
Outside it they fail with `JobNotStartedError`, which the state machine does not
retry; an already created Job is still observed. Holidays on which the node stays
off are not known to the runner. Both default schedules fall inside this window;
keep them there, or widen the window together with a dedicated node.

### Stages without a runtime yet

Validate/Import and Jev have no adapter runtime. Until they do, deploy their
Lambda ARNs with the shared handler and `ORCHESTRATION_ACTION=not_enabled`,
`PIPELINE_STAGE_NAME=validate_import` or `jev`. Such an adapter raises
`StageNotEnabledError` without touching S3, RDS or Jev, the state machine records
the run as failed and does not retry, and nothing after that stage runs. The
weekly `integrity` route also goes through the Validate/Import ARN, so it stops
the same way.

A real adapter replacing a placeholder must keep this contract:

- Input: the run contract produced by `InitializeRun` (plus `stage`, `job_name`
  and `job_status` from the previous runner). Reject a contract whose `run_id`,
  `s3.prefix` or `input_manifest_sha256` does not match.
- Output: the same contract, returned only after the stage's
  `stages.<name>.success_marker` object has been written.
- Idempotency: a rerun of the same `run_id` must reuse finished work and must
  not duplicate rows, objects or Jev calls.
- Jev: it ends at `jev/review-bundle.tar.gz` and never creates an approval
  marker; human review stays a separate step.

### Human color review (FITZZA-305)

After Jev the run stops at `WaitForHumanReview`, which invokes the shared handler
with `ORCHESTRATION_ACTION=review_requester` and waits on a Step Functions task
token:

- The token is stored at `orchestration/review/<run-id>/task-token.json`, outside
  the `pipeline/` prefix that pipeline Job roles can read, and the Job role is
  denied writes under `pipeline/runs/*/approved/`, so a Job cannot approve its own
  run. `request.json` next to the token records the bundle keys and the deadline.
- When `REVIEW_TOPIC_ARN` is set, the review instructions (download, `color_review`
  and `review_gate`, quality approval, upload command) are published to that SNS
  topic. When it is unset nothing is sent.
- The run waits at most three days (`TimeoutSeconds` 259200, kept equal to
  `REVIEW_TIMEOUT_SECONDS`) and is then recorded as failed. Waiting adds no state
  transitions.

The approval receiver (`ORCHESTRATION_ACTION=approval_receiver`, with
`PIPELINE_BUCKET` set) handles EventBridge `Object Created` events for
`pipeline/runs/<run-id>/approved/bundle.tar.gz`. It streams the bundle once and
requires `config/_APPROVED.json` with `human_color_review_approved: true` and
`config/_QUALITY_APPROVED.json` with `approved: true`, the same `files` and a
40-character `model_revision`. It then resumes the run with the bundle SHA-256
under `$.review`; a bundle that fails these checks fails the run with
`ApprovalRejected`, and a corrected bundle needs a new run. `embed_job` still
re-verifies the full fingerprint. The decision is written once to
`orchestration/review/<run-id>/decision.json`; other objects, other buckets and
runs without a pending request are ignored.

Both are off by default in the stack. `EnableReviewNotification=true` creates
the SNS topic, plus an email subscription when `ReviewNotificationEmail` is set
(the address must confirm it). `EnableApprovalEvents=true` with
`ApprovalReceiverLambdaArn` creates the EventBridge rule and the invoke
permission; the data bucket must also have EventBridge notifications turned on,
which this stack does not change. The Lambda roles are not part of the stack and
need:

- review requester: `s3:PutObject` on `orchestration/review/*`, and `sns:Publish`
  on the topic when notifications are on;
- approval receiver: `s3:GetObject` on `pipeline/runs/*/approved/bundle.tar.gz`
  and `orchestration/review/*`, `s3:PutObject` on
  `orchestration/review/*/decision.json`, `s3:ListBucket` limited to the
  `orchestration/review/` prefix (so a missing request reads as 404, not 403),
  and `states:SendTaskSuccess` and `states:SendTaskFailure` on the state machine.

Everything above is defined but switched off. What still has to be decided,
implemented and deployed before the pipeline can run on a schedule, with costs
and rollback, is in [AUTOMATION_READINESS.md](AUTOMATION_READINESS.md) (Korean).

The Job service account `fitzza-pipeline` is defined in
`infra/data-pipeline/pipeline-service-account.yaml`. Like the other pipeline
manifests in this directory it is applied manually; it is not part of the CD
kustomization, so merging this code does not create it in the cluster.

## Local Qdrant

Qdrant runs in Docker; the crawler validation and Jev scripts run as Python batch jobs.

```powershell
docker compose -f infra/data-pipeline/docker-compose.yml up -d
docker compose -f infra/data-pipeline/docker-compose.yml ps
```

Open `http://localhost:6333/dashboard` for the Qdrant dashboard. Stop it without deleting indexed data:

```powershell
docker compose -f infra/data-pipeline/docker-compose.yml down
```

### Postman checks

- `GET http://localhost:6333/collections`: Qdrant connection and collection list
- `GET http://localhost:6333/collections/musinsa_products`: collection status after indexing
- `POST http://localhost:6333/collections/musinsa_products/points/scroll`: inspect indexed payloads

Use this JSON body for the scroll request:

```json
{
  "limit": 3,
  "with_payload": true,
  "with_vector": false
}
```

Jev and FashionCLIP are batch scripts, not HTTP APIs, so they are verified through generated files and logs rather than Postman. The current FashionCLIP script recreates `musinsa_products`; use it only against this local Qdrant instance until that behavior is made configurable.
