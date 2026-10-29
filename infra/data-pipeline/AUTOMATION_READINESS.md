# 데이터 파이프라인 자동화 활성화 준비 (FITZZA-306)

주기 수집 → Jev 색상 정규화 → 사람 검수 → FashionCLIP 임베딩 → Qdrant 적재 자동화를 나중에 켤 때 필요한
형식과 순서를 정리한다. 2026-10-29 기준으로 **아무것도 켜져 있지 않다.** 이 문서는 배포·예약 활성화·권한 확대의
승인이 아니며, 표에 "승인"으로 표시한 단계는 진행 전에 담당자 승인을 받는다.

관련 이슈: FITZZA-302(준비 범위), FITZZA-304(오케스트레이션 반영), FITZZA-305(사람 검수 대기·승인 수신), FITZZA-219·290.
구성 설명은 [README.md](README.md)의 "Orchestration run contract" 절, 수동 검수 절차는 [DEPLOYMENT.md](DEPLOYMENT.md)를 본다.

## 1. 현재 상태 (develop `61908b7`)

| 구성 | 상태 |
| --- | --- |
| 상태 머신 정의(`orchestration.asl.json`)·스택 템플릿(`orchestration.yaml`) | 저장소에만 있음. AWS 정의 검증 OK, 배포 안 함 |
| 예약 실행 | `ScheduleState` 기본 `DISABLED`. 기본 시각은 실행 창 안(증분 화·목 10:00, integrity 월 11:00 KST) |
| Crawler·FashionCLIP runner | 코드 있음. 한 번 호출에 최대 10분 대기, 상태 머신이 5분마다 재확인. 새 Job은 평일 09:30~16:00 KST에만 생성 |
| 사람 검수 대기·알림·승인본 수신 | 코드 있음. 알림(SNS)·승인 이벤트(EventBridge) 기본 꺼짐 |
| Validate/Import, Jev 단계 | 자리 어댑터(`not_enabled`). 호출되면 아무것도 바꾸지 않고 실행이 멈춤 |
| 주간 integrity | Job 이미지(`data-pipeline-integrity`)와 Job spec은 있으나 상태 머신이 Validate/Import 자리로 보내 멈춤 |
| 크롤러 증분 수집 | 미구현. runner가 넘기는 `PIPELINE_*` 환경 변수를 크롤러가 읽지 않음 |
| 승인 색상 사전·증분 벡터 적재 | 이 문서의 4·5절에 형식과 방식만 정의. 코드 없음 |

## 2. 켜기 전에 정할 것

| # | 항목 | 선택지 | 권장(안) |
| --- | --- | --- | --- |
| 1 | 실행 주기·시간 | 운영 시간 안 주 1~2회 / 매일 새벽(전용 노드 필요) | 운영 시간 안 주 1~2회. 추가 비용 없음 |
| 2 | 검수 알림 채널 | SNS 이메일 / Jira 하위 작업 자동 생성 / 메신저 웹훅 | SNS 이메일(템플릿에 있음) |
| 3 | 사전에 있는 색상의 재검수 | 재검수 없이 인정 / `human_decision`만 인정 / 매번 재검수 | 처음 2~3회는 매번 재검수, 이후 `human_decision`만 인정 |
| 4 | 새 색상이 0건인 실행 | 사람 승인 유지 / 자동 통과 | 사람 승인 유지. 품질 승인(`_QUALITY_APPROVED.json`)은 실행마다 필요해 현재 구조로는 자동 통과 불가 |
| 5 | alias 전환 | 가드 통과 시 자동 / 매번 사람 확인 | 처음에는 매번 사람 확인 |
| 6 | 승인본 업로드 주체 | 운영자 / 검수자(쓰기 권한 확대) | 운영자 |
| 7 | 실행 노드 | 공용 노드(현재) / 전용 파이프라인 노드(EC2 비용) | 공용 노드 |

## 3. 켜기 전에 구현할 것

1. **크롤러 증분 모드**: 계약의 `run_mode`, 기준 manifest, checkpoint(`PIPELINE_BASELINE_MANIFEST_KEY` 등)를 읽어 신규·변경 상품만 수집하는 진입점. 지금 크롤러는 `discover`·`hydrate` 같은 하위 명령을 인자로만 받는다.
2. **Validate/Import 어댑터**: 검증과 RDS 반영(FITZZA-286 범위). README의 자리 어댑터 계약(입력 확인, 성공 표지 기록 후 반환, 멱등)을 지킨다. 상품 DB는 벡터보다 먼저 반영한다.
3. **Jev 어댑터**: Jev Job을 실행한다. `job_spec.py`의 단계 목록에 `jev`가 없으므로 추가하거나 별도 runner를 둔다. 결과는 `jev/review-bundle.tar.gz`까지이고, 검수 대상 수를 `review_required_count`로 계약에 넘기면 알림에 표시된다.
4. **FashionCLIP 단계 연결**: `embed_job` → `import_job` → (가드) → `switch_alias`를 실행 계약 값(run_id, vector run id, 컬렉션 이름)으로 순서대로 실행한다. 지금 runner는 고정 명령 하나만 실행한다.
5. **integrity 경로**: 상태 머신의 `RunIntegrityChecks`를 Validate/Import 자리 대신 integrity runner(`PIPELINE_STAGE=integrity`)로 보낸다.
6. **승인 색상 사전 연결**(4절), **증분 벡터 적재와 alias 가드**(5절), **초대형 이미지 리사이즈**(5절).
7. **runner 권한 축소**: 스택이 runner 역할에 붙이는 `AmazonEKSEditPolicy`는 fitzza 네임스페이스 전체(Secret 포함) 편집 권한이다. 전용 Kubernetes 그룹과 Job 생성·조회만 허용하는 Role/RoleBinding으로 바꾼다(`fitzza-delivery`와 같은 방식).

## 4. 승인 색상 사전

목적: 사람이 승인한 `color_raw → 색상` 매핑을 실행 사이에 이어서, 처음 보는 색상명만 Jev 호출·검수 대상이 되게 한다.
지금은 Jev 결과 재사용이 같은 실행 안(`pipeline/runs/<run-id>/jev/color_map_jev_results.jsonl`)에서만 되므로,
주기 실행마다 같은 색상이 다시 검수 대상이 된다.

- 형식: [color-dictionary.schema.json](color-dictionary.schema.json), 예시 [color-dictionary.example.json](color-dictionary.example.json).
  색상 18종은 `review_gate.py`의 `COLORS`와 같다.
- 저장: `pipeline/color-dictionary/v<NNNN>.json`을 create-only로 쓰고, 지금 쓰는 버전은 `pipeline/color-dictionary/current.json`
  (`{"version": "v0001", "sha256": "..."}`)으로 가리킨다. 이전 버전은 지우지 않는다. 쓰기는 운영자만 한다.
- 항목 출처(`basis`)
  - `human_decision`: 승인본의 `reviewed_colors.json`에 있는 항목(사람이 직접 고른 값)
  - `approved_jev`: 확신이 기준(0.6) 이상이라 개별 검수 없이 승인본에 포함된 Jev 결과
- 새 버전 만들기: 색상·품질 승인을 통과한 승인본의 `config/color_map.json`과 `config/reviewed_colors.json`으로 이전 버전에 항목을 더한다.
  같은 `color_raw`의 색상이 바뀌는 경우는 덮어쓰지 않고 목록으로 뽑아 사람이 정한다.
- 연결 지점(코드 변경 필요)
  - `jev_job.py`: `current.json`이 가리키는 사전을 받아, 사전에 있는 색상명은 Jev에 묻지 않는다. 사용한 사전을 `config/color_dictionary.json`으로 번들에 넣는다.
  - `generate_color_map.py`: `todo`에서 사전 항목을 빼고 `color_map.json`에 사전 값을 넣는다.
  - `review_gate.py`: 2절 3번 결정에 따라, 사전 항목을 필수 검수 대상에서 뺄 수 있게 한다. `config/color_dictionary.json`을 승인 fingerprint의 `files`에 포함한다.
    지금은 기존 overrides도 사람이 매번 확인해야 하며, 사전은 출처(승인 실행·번들 SHA-256)가 남는다는 점이 overrides와 다르다.

## 5. 증분 벡터 적재

`import_job`은 vector run 하나로 새 버전 컬렉션을 만든다. 증분 실행의 vector run에는 신규·변경 상품만 있으므로 그것만으로는 전체 컬렉션이 되지 않는다.

1. 변경 판정: 이번 승인본과 이전 승인 manifest를 상품별 SHA-256으로 비교해 신규·변경·제외(판매 종료) 상품을 나눈다.
2. 신규·변경 상품만 `embed_job`으로 임베딩해 새 vector run을 만든다. 모델 revision이 기준과 다르면 합치지 않고 전체를 다시 임베딩한다.
3. 합집합 구성: 현재 alias가 가리키는 컬렉션의 vector run에서 변경·제외 상품의 점을 **상품 단위로 전부** 빼고, 새 vector run의 점을 더한다.
   점 ID는 `uuid5(product_id|variant_key|image_key)`라 같은 이미지는 같은 ID지만, 색상·이미지가 줄어든 상품의 옛 점이 남지 않도록 상품 단위로 교체한다.
4. 합친 레코드로 새 버전 컬렉션(`fitzza_products_<YYYYMMDD>_<NN>`)을 만들고 `import_job`의 검증 8항목을 통과시킨다. S3의 벡터를 쓰므로 재임베딩은 없다.
5. 가드를 모두 통과하면 `switch_alias --apply`로 전환하고, 스냅샷을 `backups/qdrant/<collection>/`에 남긴다(`infra/k8s/QDRANT.md`).

alias 전환 가드(안):

| 가드 | 기준 |
| --- | --- |
| 검증 | `import_job` 검증 8항목 모두 true, 실패 batch 0 |
| 점 수 | 현재 alias 대상보다 5% 넘게 줄면 보류. 판매 종료가 원인이면 사람이 확인 후 진행 |
| 색상 | 미매핑 색상 0건 |
| 순서 | 같은 실행의 Validate/Import 성공 표지 존재(상품 DB가 먼저 반영됨) |
| 모델 | 기준 컬렉션과 같은 `model_revision` |

- 보존: 현재 대상과 직전 2개 컬렉션을 남긴다. 더 오래된 컬렉션 삭제는 사람 승인 후 한다.
- 초대형 이미지: `embed_job`은 2천만 픽셀을 넘는 이미지를 실패로 기록한다(290에서 22개). 긴 변 기준으로 줄여 임베딩하고 payload에 축소 여부를 남기는 단계를 넣는다.

## 6. 활성화 순서

### A. 결정과 구현

- [ ] 2절 항목 결정, Jira에 기록
- [ ] 3절 구현 완료(develop 병합, CI 통과)

### B. AWS 준비 (승인 필요: 자원 생성·권한 확대)

- [ ] **B1. Lambda ZIP**: `python scripts/package_orchestration_lambda.py --output build/orchestration-adapters.zip`. 의존성 없음(boto3는 Lambda 런타임 제공)
- [ ] **B2. Lambda 함수 8개**: Python 3.12, arm64, 로그 보존 7일

  | 함수(이름 안) | 핸들러 | 환경 변수 | 제한 시간 | 필요한 권한 |
  | --- | --- | --- | --- | --- |
  | `fitzza-prod-pipeline-initialize` | `infra.aws.orchestration.handler.lambda_handler` | `ORCHESTRATION_ACTION=initialize_run`, `PIPELINE_BUCKET`, `PIPELINE_BASELINE_MANIFEST_KEY`, `PIPELINE_INCREMENTAL_CHECKPOINT_KEY`(기본 `pipeline/state/incremental.json`) | 30초 | 기준 manifest·checkpoint `s3:GetObject`, `pipeline/state/` 한정 `s3:ListBucket`(없는 checkpoint를 404로 받기 위함) |
  | `fitzza-prod-pipeline-status-writer` | 같음 | `ORCHESTRATION_ACTION=status_writer` | 30초 | `pipeline/runs/*/status/*` `s3:PutObject` |
  | `fitzza-prod-pipeline-crawler-runner` | `infra.aws.orchestration.runner_lambda.lambda_handler` | `PIPELINE_STAGE=crawler`, `PIPELINE_IMAGE`, `PIPELINE_COMMAND_JSON`, `EKS_CLUSTER_NAME`, `EKS_NAMESPACE`, `PIPELINE_JOB_WAIT_SECONDS`(600), `PIPELINE_RUN_WINDOW`, `PIPELINE_NODE_SELECTOR_JSON` | 720초(대기 시간보다 길게) | VPC 사설 서브넷 + ENI 권한, `eks:DescribeCluster`·EKS 접근 항목(스택이 부여) |
  | `fitzza-prod-pipeline-fashion-clip-runner` | 같음 | `PIPELINE_STAGE=fashion-clip`, 나머지 같음 | 720초 | crawler runner와 같은 역할 |
  | `fitzza-prod-pipeline-validate-import` | handler | `ORCHESTRATION_ACTION=not_enabled`, `PIPELINE_STAGE_NAME=validate_import` (3절 2번 전까지) | 10초 | 로그만 |
  | `fitzza-prod-pipeline-jev` | handler | `ORCHESTRATION_ACTION=not_enabled`, `PIPELINE_STAGE_NAME=jev` (3절 3번 전까지) | 10초 | 로그만 |
  | `fitzza-prod-pipeline-review-request` | handler | `ORCHESTRATION_ACTION=review_requester`, `REVIEW_TOPIC_ARN`(알림을 켤 때) | 30초 | `orchestration/review/*` `s3:PutObject`, 주제 `sns:Publish` |
  | `fitzza-prod-pipeline-approval-receiver` | handler | `ORCHESTRATION_ACTION=approval_receiver`, `PIPELINE_BUCKET` | 120초 | 승인본·`orchestration/review/*` `s3:GetObject`, `decision.json` `s3:PutObject`, `orchestration/review/` 한정 `s3:ListBucket`, 상태 머신 `states:SendTaskSuccess`·`SendTaskFailure` |

  runner 두 개는 같은 역할을 쓰고 VPC 사설 서브넷에 둔다. EKS API 공개 접근이 운영자 IP로 제한돼 있어 private endpoint로 붙어야 하며,
  Lambda 보안 그룹에서 클러스터 보안 그룹 443을 허용한다. `eks:DescribeCluster`는 NAT를 거친다.
- [ ] **B3. runner 권한 축소**(3절 7번)를 스택에 반영
- [ ] **B4. ServiceAccount**: `kubectl apply -f infra/data-pipeline/pipeline-service-account.yaml`(CD 대상 아님)
- [ ] **B5. 상태 머신 정의 업로드**: 버전 관리가 켜진 비공개 버킷에 `orchestration.asl.json`을 올리고 버전 ID를 기록
- [ ] **B6. 스택 배포**: [orchestration-parameters.example.json](../aws/cloudformation/orchestration-parameters.example.json)을 채워 change set으로 만들고, 변경 내용을 확인한 뒤 실행.
  처음에는 `ScheduleState=DISABLED`, `EnableApprovalEvents=false`
- [ ] **B7. 알림**: `EnableReviewNotification=true`(+`ReviewNotificationEmail`)로 갱신하고 구독 확인 메일을 수락. 출력 `ReviewNotificationTopicArn`을 review-request 함수의 `REVIEW_TOPIC_ARN`에 넣는다
- [ ] **B8. 승인 이벤트**: 데이터 버킷의 EventBridge 알림을 켜고(foundation 스택 변경), `EnableApprovalEvents=true`와 `ApprovalReceiverLambdaArn`으로 갱신

### C. 소량 수동 실행 (운영 시간 안)

- [ ] 운영 시간 안에 소량 입력으로 시작. `{"run_mode":"incremental"}`를 `run-input.json`에 저장하고
  `aws stepfunctions start-execution --state-machine-arn <StateMachineArn> --input file://run-input.json --profile fitzza --region ap-northeast-2`
  (PowerShell에서 JSON을 직접 넘기면 큰따옴표가 빠질 수 있어 파일로 넘긴다)
- [ ] 단계별 상태 문서(`pipeline/runs/<run-id>/status/`), Job 생성·재사용, 검수 알림 수신 확인
- [ ] 정상 승인본 업로드 → 실행 재개, 승인 파일이 빠진 번들 → `ApprovalRejected` 실패 확인
- [ ] 결과와 비용을 Jira에 기록

### D. 예약 켜기 (승인 필요)

- [ ] 예약 시각 확인. 기본값(예시 파일과 같음)은 증분 `cron(0 1 ? * TUE,THU *)`(화·목 10:00 KST),
  integrity `cron(0 2 ? * MON *)`(월 11:00 KST)이다. EventBridge 규칙의 cron은 UTC 기준이므로,
  2절 1번 결정이 다르면 UTC로 바꿔 넣고 실행 창(평일 09:30~16:00 KST) 안에 두는지 확인한다
- [ ] `ScheduleState=ENABLED` change set 실행, 첫 예약 실행 결과 확인
- [ ] 노드가 쉬는 공휴일·제외일은 runner가 모른다. 그날도 실행 창 시간이면 runner가 Job을 만들고,
  노드가 없어 Pod가 `PENDING`으로 남으면 상태 머신이 300초마다 다시 확인한다. Job의
  `activeDeadlineSeconds`(6시간)가 지나면 Job이 실패하고, runner 재시도 후 `RecordFailure`가 실패를 기록한다.
  그날 예약을 미리 끄거나 실행을 중단하면 6시간 대기를 피할 수 있다

## 7. 예상 비용 (추정, 켜기 전에 다시 확인)

| 항목 | 추정 | 근거 |
| --- | --- | --- |
| Step Functions(Standard) | 실행 1회 약 80 상태 전이(크롤링·임베딩 각 1시간, 5분 간격 확인 기준), 주 2회면 월 약 700건 | 월 4,000건 무료(12개월 후에도 유지). 검수 대기 중에는 전이 없음 |
| Lambda | runner가 5분마다 최대 10분씩 호출. 메모리 256MB 기준 실행 1회 수천 GB-초 | 계정의 무료 사용량 조건에 따라 다름. 비용 탐색기로 확인 |
| SNS 이메일 | 실행당 1건 | 월 1,000건 무료 |
| EventBridge(예약·S3 이벤트) | 주 몇 건 | 무시할 수준으로 예상. 요금 페이지로 확인 |
| CloudWatch Logs | 함수 8개 로그 | 보존 7일로 제한 |
| NAT 데이터 처리 | runner의 `eks:DescribeCluster` 호출 정도 | 소량 |
| 전용 노드·새벽 기동 | 2절 7번에서 전용 노드를 고를 때만 발생 | EC2 비용, 별도 승인 |

## 8. 되돌리는 방법

| 상황 | 방법 |
| --- | --- |
| 새 실행을 막기 | `ScheduleState=DISABLED` change set |
| 진행 중 실행 중단 | `aws stepfunctions stop-execution --execution-arn <arn>` (이미 만든 Job은 `kubectl -n fitzza delete job <name>`, 승인 후) |
| 승인 이벤트 끄기 | `EnableApprovalEvents=false` |
| 알림 끄기 | review-request 함수의 `REVIEW_TOPIC_ARN` 제거 또는 `EnableReviewNotification=false` |
| 잘못 전환된 alias | `switch_alias`가 출력한 이전 대상으로 다시 전환(컬렉션은 지우지 않음) |
| 전체 철거 | 스택 삭제. 스택이 만든 상태 머신, 예약·승인 이벤트 규칙, SNS 주제·구독, Lambda 호출 권한과 함께 `PipelineJobRole`, `PipelineJobPodIdentity`, `RunnerLambdaEksDescribePolicy`, `RunnerLambdaEksAccessEntry`, `StateMachineRole`, `ScheduleRole`도 삭제된다. 스택 밖의 Lambda 함수·역할과 S3 데이터는 남지만, EKS 접근 항목과 Pod Identity가 없어져 그 함수로 Job을 만들거나 Job이 S3에 접근할 수 없으므로 다시 쓰려면 스택을 다시 배포해야 한다 |
