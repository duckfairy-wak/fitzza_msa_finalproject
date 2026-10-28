# 배포 상태와 실행 분리

기준: 2026-10-21 KST. 이 문서의 배포는 실제 크롤링·Jev 호출·임베딩·적재를 승인하지 않는다.
새 Job은 모두 `suspend: true`이며 `--execute-approved-run`도 의도적으로 빠져 있다.
정지만 해제해도 데이터 작업은 실행되지 않는다. 자동 CronJob/EventBridge 실행은 구성하지 않는다.

## 구성

| 단계 | 준비 리소스 | 다음 단계 조건 |
| --- | --- | --- |
| 신규 수집 | crawler-collection-prepared / src.cloud_batch | 500개 seed ID 제외, 실행별 체크포인트 |
| 데이터 계약·선정 | data-curation-prepared / src.cloud_curate | 3000개 고유 상품·목표 비율·의류 계절·실측·색상 이미지 연결 검사; 실제 이미지 내용 검증은 별도 |
| Jev 색상 정제 | jev-color-20261025-01 / src.jev_job | SSM 키 등록 및 curated/manifest.json + curated/data/ (기본) 또는 curated/bundle.tar.gz |
| 사람 검수 | 로컬 review-bundle / src.review_gate | 미확정 색상 및 기존 overrides의 명시적 재검수 |
| 인덱싱 | fashion-clip-indexer-prepared / indexer/entrypoint.py | 색상 승인 + 품질 승인 + 모델 revision 고정 |

기존 500개는 카테고리당 100개·중복 0개다. 모두 품질 검증을 통과한다면 추가 목표는
상의 800 / 하의 650 / 신발 500 / 아우터 350 / 모자 200이다. seed manifest는 수량·hash 목록이며 품질 승인본이 아니다.
raw batch 성공과 screened 수량을 최종 합격 상품 수로 간주하지 않는다.

## 소스 및 이미지

- 크롤러: 이 브랜치 `crawler/src`; Python 3.12, Playwright 1.55.0, ARM64.
- Jev·인덱서 기준: `2kmkmkm/fashion-CLIP`, `feat/color-map-jev`, commit `1568de39e17cde9fb229b30f78b53f80b2a891f5`.
- `feat/docker-qdrant-data`의 인덱서는 동일하다. 해당 Dockerfile의 스냅샷 자동 복구는 기존 EKS Qdrant에 적용하지 않는다.
- 배포 어댑터는 기존 컬렉션 삭제 금지, staging 전용, 4개 이미지 단위 임베딩, 승인 확인을 추가했다.
- 모델 런타임 기반은 운영 recommendation-service digest `sha256:d9ae634c8119cb5e5e36ed4d1311115c350f2519c25bba6e03737ccd704b3c7b`다.
- 모델 가중치는 빌드·배포 중 내려받거나 실행하지 않는다. 실제 인덱싱 시 품질 승인 manifest에 지정한 모델 commit SHA를 사용한다.

## S3 계약

버킷: `fitzza-prod-foundation-databucket-wwng6wfc0hqy`
다음 실행 prefix: `pipeline/runs/collection-20261022-01/` (날짜는 식별자이며 예약 실행이 아님).

```text
seed/manifest.json                # seed 후보 ID·hash
seed/objects/<sha256>             # manifest와 동일한 기존 상품 JSON; 실제 실행 전 별도 게시 필요
crawler/objects/<sha256>           # raw 체크포인트, 내용 주소 기반
crawler/checkpoints.json           # 경로→hash 목록, ETag 조건부 게시
curated/bundle.tar.gz              # 품질·선정 후 data/**/*.json을 운영자가 게시
jev/color_map_jev_results.jsonl    # 재사용 가능한 Jev 응답
jev/review-bundle.tar.gz           # data/ + config/, 사람 검수 다운로드
approved/bundle.tar.gz             # 사람이 검수하고 품질 검증한 승인본
indexer/report.json                # 적재 후 보고서, 서빙 전환 아님
```

### Jev 입력 (2026-10-27)

`collection-20261025-01`은 전체 수집 Job(`src.cloud_full_run`)이 만든 실행이라 `curated/bundle.tar.gz`가 없고
`curated/manifest.json` + `curated/data/<카테고리>/<상품ID>.json`만 있다.
`src.jev_job`의 기본 입력(`--input-layout manifest`)은 manifest의 각 행을 검사한 뒤 상품 JSON을 받는다.

- 경로는 `<category>/<product_id>.json`, S3 키는 같은 실행의 `curated/data/` 아래여야 한다.
- 상품 ID 중복, 파일 SHA-256 불일치, 본문 `product_id` 불일치가 하나라도 있으면 Jev를 호출하지 않고 실패한다.
- 기존 `curated/bundle.tar.gz` 입력은 `--input-layout bundle`로 유지한다.
- 이전 Jev 응답 파일은 정확한 키 목록 조회로 존재를 확인한다. 목록 권한 없이 없는 객체를 읽으면 S3가 403을 돌려주기 때문이다.
- `jev-policy.json`은 이 실행의 manifest·상품 JSON 읽기, 이전 응답 파일 하나의 존재 확인, `jev/` 쓰기만 허용한다.
- 기존 정지 Job `jev-color-review-prepared`는 템플릿을 바꿀 수 없으므로, 새 이름 `jev-color-20261025-01`로 만든다.
  새 이미지 태그 `jev-manifest-20261027-01`을 ECR에 올린 뒤 적용한다. `suspend: true`와 실행 플래그 미포함은 그대로다.

raw→curated 연결 코드·이미지·전용 IAM·정지 Job 대기 배포를 완료했다. 실제 실행 검증은 아직 하지 않았다.
10/22 parser에 실제 Options.basic COLOR_CHIP → 활성 optionItem의 동일 goodsNo/optionValueNos 연결을 추가했다.
이 연결이 증명되는 imageUrl만 color_image_mappings로 보존하며 원래 색상 이름은 변경하지 않는다.
삭제/비활성/타 상품 옵션·크기 옵션·공통 색상칩·공유 placeholder·허용되지 않은 이미지 URL은 제외한다.
요청 상품 ID와 반환 Detail ID가 다르면 수집은 실패한다. 상품명·대표 썸네일 추측은 하지 않는다.
로컬 HTML 3개(동일 상품 7213384의 저장본)에서 각각 6개 연결을 오프라인 확인했다.
OtherColorGoods의 비어 있지 않은 실제 원본 fixture가 없어 그 경로는 아직 구현하지 않았다.
따라서 명시적 COLOR_CHIP 이미지가 없는 상품은 정제 입력으로 승격되지 않는다.
이 변경의 ECR/정지 Job 반영, 실제 이미지 내용 검증 및 전체 단계 오케스트레이션은 아직 하지 않았다.
FITZZA-219 완료나 전체 end-to-end 검증 완료로 기록하지 않는다. 운영자 입력 없이 raw를 Jev에 바로 넘기지 않는다.
checkpoint는 같은 실행에서 직렬 Job으로만 갱신한다. ETag 충돌은 실패이며 강제로 덮어쓰지 않는다.
새 worker는 이전 pilot 경로를 자동 합치지 않는다.

## 키 등록 (사용자가 직접, 실제 호출과 별도)

일반 대화·파일·명령행 인자에 키를 붙여 넣지 않는다. 대화형 PowerShell에서 아래를 실행하고 숨김 프롬프트에 입력한다.

```powershell
py -m venv "$env:TEMP\fitzza-key-register"
& "$env:TEMP\fitzza-key-register\Scripts\python.exe" -m pip install "boto3[crt]>=1.41.0"
& "$env:TEMP\fitzza-key-register\Scripts\python.exe" C:\Users\user\.codex\worktrees\crawler-cloud-pipeline\backend_project\infra\data-pipeline\register_jev_key.py
```

스크립트는 `fitzza` 프로필로 `/fitzza/prod/data-pipeline/typesafe-api-key`를 Standard SecureString으로 새로 등록한다.
기존 값은 덮어쓰지 않으며 키를 출력하지 않는다. 이 스크립트는 배포 과정에서 자동 실행하지 않는다.
Jev Job은 실행 승인을 받은 경우에만 해당 파라미터를 복호화해 자식 프로세스에 전달한다.
Secrets Manager 자원은 새로 만들지 않는다.
10/21 사용자가 등록을 완료했고, describe-parameters로 SecureString version 1 메타데이터만 확인했다.
키 값은 읽지 않았고 Jev 호출도 하지 않았다. 기존 크롤러 가상환경은 변경하지 않는다.

## raw → curated 연결 (배포와 실제 실행은 별도)

컨테이너의 `/app` 또는 소스 `crawler` 폴더에서 다음은 로컬 JSON만 읽는다.
`--source` 순서대로 seed와 신규 screened 디렉터리를 입력한다. 원본은 수정하지 않는다.

```powershell
python -B -m src.curate_dataset --source <seed-data> --source <screened-data>
```

이 명령은 수량·탈락 사유·부족량을 출력한다. `--bundle <새-파일.tar.gz>`를 추가하면
카테고리별 900/750/600/450/300 및 의류 계절 quota 충족 때만 `data/`와 `config/curation_report.json`을 만든다.
동일 ID 중복은 실패하고, 기존 번들은 덮어쓰지 않는다. 이미지 내용 확인이나 색상·품질 승인 파일은 생성하지 않는다.
색상 이름이나 이미지가 없을 때 상품명에서 추측하거나 다른 상품 이미지를 복사하지 않는다.

`src.cloud_curate --bucket <bucket> --run-id <run-id>`는 기본적으로 네트워크 호출 0회다.
별도 실행 승인 후 `--execute-approved-run`이 지정된 때만 S3 seed manifest/objects와
동일 실행의 screened 체크포인트를 읽고 SHA-256을 검증한다. 후보·탈락·실패 기록은 입력에서 제외한다.
선정 완료 시 `curated/bundle.tar.gz`를 `IfNoneMatch=*`로 최초 게시한다. 미완료면 게시 없이 실패하며 Jev는 시작하지 않는다.
이는 단계 간 데이터 연결이며 자동 단계 실행기가 아니다. 실제 사용 전 입력 객체 준비가 필요하다.
`curator-job.yaml`은 `fitzza-curator` 서비스 계정을 사용하며 전용 `fitzza-prod-curator` 역할에 연결됐다.
IAM은 이번 실행의 seed/체크포인트 읽기와 `If-None-Match: *`가 있는 curated 번들 생성만 허용한다.
앱·CD·기존 수집 역할은 변경하지 않았으며 삭제·SSM 키 읽기·승인본 쓰기 권한은 없다.
Autopilot 정적 분석 baseline에서 S3 Get/Put만 남기고 실제 입력·출력 경로로 제한했다.
분석 도구의 `WILDCARD_WITHOUT_LIKE_OPERATOR` 경고 1건은 literal `*` 헤더 비교에 관한 것이다.
이 값은 와일드카드 패턴이 아니므로 정확한 `StringEquals`를 유지했다. 권한 시뮬레이터에서
조건부 Put 허용, 헤더 없는 Put·Delete·SSM 읽기 차단을 확인했다. 실제 Pod AWS 호출 검증은 별도다.
임시 Docker 인증 설정은 push 후 로그아웃했다.

기존 500개 오프라인 검사 결과: 488개 계약 통과, 12개 `invalid_actual_size`로 제외.
통과량은 상의 98 / 하의 96 / 신발 96 / 아우터 99 / 모자 99, 추가 부족량은 802/654/504/351/201이다.
검사 기준은 모든 사이즈 행에 인덱서가 인식하는 유한 양수 실측값이 있는지다. 일부 행만 사용 가능한 상품도 제외한다.
488개는 현재 입력 계약 통과 수량이지 최종 이미지 품질·사람 검수 합격 수량이 아니다.

## 사람 검수와 승인

검수 번들에 `data/`와 `config/`가 있어야 한다. `color_map_review.csv`의 모든 항목과 적용된 기존 overrides를 확인한다.
최종 선택을 `color_map.json`에 반영하고, 직접 확인한 색상의 `{정규화된 원래 이름: 최종 색상}`을 `reviewed_colors.json`에 기록한다.
기존 overrides 파일 존재만으로 검수 완료로 간주하지 않는다.

```powershell
python crawler/src/review_gate.py approve --bundle <검수한-번들-폴더>
python crawler/src/review_gate.py verify --bundle <검수한-번들-폴더>
```

### 검수 도구 (`crawler/src/color_review.py`)

Jev Job이 올린 `jev/review-bundle.tar.gz`를 받아 배포 직전 승인본까지 만든다. AWS·Jev·모델·Qdrant를 호출하지 않는다.
`crawler` 폴더에서 실행한다(번들 경로는 절대 경로 권장).

```bash
aws s3 cp s3://<bucket>/pipeline/runs/<run-id>/jev/review-bundle.tar.gz <작업폴더>/ --profile fitzza
tar -xzf <작업폴더>/review-bundle.tar.gz -C <작업폴더>
python -m src.color_review page --bundle <작업폴더>            # <작업폴더>-color-review.html 생성
python -m src.color_review apply --bundle <작업폴더> --decisions <review_decisions.json>
python -m src.review_gate approve --bundle <작업폴더>
python -m src.review_gate verify --bundle <작업폴더>
python -m src.color_review package --bundle <작업폴더> --output <color-approved.tar.gz>
```

- `page`: `review_gate`가 사람 확인을 요구하는 색상(review CSV 전부, 이 데이터셋에 쓰인 overrides, etc·multi)만 실제 상품 사진·Jev 후보와 함께 보여준다. 검수 결과는 `review_decisions.json`으로 저장한다.
- `apply`: 대상이 하나라도 빠졌거나 허용되지 않은 색이면 아무것도 바꾸지 않는다. 통과하면 `color_map.json`과 `reviewed_colors.json`을 쓴다. 이미 `_APPROVED.json`이 있으면 거부한다.
- `package`: 인덱서(`indexer/entrypoint.py`)와 같은 규칙으로 색상 승인·상품 3000개를 확인하고 `data/`·`config/`만 담은 tar.gz를 만든다. 만든 파일을 인덱서와 같은 방식으로 다시 풀어 같은 검사를 한 번 더 한다. 같은 번들이면 같은 파일(SHA-256)이 나온다.
- 품질 승인(`config/_QUALITY_APPROVED.json`)을 넣은 뒤 `--require-quality`로 다시 만든 파일이 `approved/bundle.tar.gz`로 올릴 최종본이다. 이 옵션 없이 만든 파일은 색상 승인본이며 인덱서가 거부한다.
- 업로드는 운영자가 한다: `aws s3 cp <최종본> s3://<bucket>/pipeline/runs/<run-id>/approved/bundle.tar.gz --profile fitzza`

이 명령은 색상 승인만 생성한다. 실측·이미지·비율·3000개 품질 검증을 대신하지 않는다.
별도 품질 검증 후 `config/_QUALITY_APPROVED.json`에 `approved: true`, 같은 파일 목록/hash(`files`),
FashionCLIP 모델의 40자리 commit SHA(`model_revision`)를 기록한다. 이 파일을 임의로 만들거나 검증 없이 true로 설정하지 않는다.
색상 승인 후 데이터·매핑·검수 결과 변경 시 승인을 다시 받아야 한다. 승인본 게시 권한은 Job에 부여하지 않는다.
인덱서는 3000개·승인 fingerprint 일치·고정 모델 revision이 없으면 Qdrant 연결 전에 실패한다.

## 운영 및 후속

- 오늘 추가 서비스 중단·수집·Jev 호출·임베딩·적재는 하지 않는다. 내일도 별도 실행 지시 전까지 정지 상태 유지.
- 실행 전 단일 노드 용량, 유지보수 대상과 원래 replica/CD 상태, 업무시간 09~18시를 다시 확인한다.
- 기존 pilot 복구 스크립트는 10/21 전용 기록이며 새로운 전체 수집 실행기로 사용하지 않는다.
- staging 컬렉션만 생성한다. 운영 컬렉션·PVC·추천 서비스 연결·alias는 자동 변경하지 않는다.
- 실패한 staging 컬렉션은 자동 삭제하지 않는다. 동일 이름이 있으면 실패하므로 재시도 시 새 staging 실행 식별자가 필요하다.
- 각 Job의 IAM은 입력 읽기와 해당 단계 결과 쓰기로 분리한다. 앱·CD 역할은 변경하지 않는다.
- IAM 정책 재검토 시 정적 분석: `uvx iam-policy-autopilot@latest generate-policies <runtime-source-absolute-path> --region ap-northeast-2 --account 414901227428 --service-hints s3 ssm --pretty`.
- 빌드·네트워크 차단 테스트·서버 dry-run은 실행 검증과 구분한다. 실제 모델 추론과 3000개 적재 검증은 아직 하지 않았다.

## 앞선 실행 이력 (새 실행 승인 아님)

10/21에 요청 해석 오류로 pilot에서 상의 후보 80개·상세 5개를 수집했다. 결과는 별도 `crawler-pilot-20261021-01` prefix에 보존했다.
pilot은 종료·정지됐고 두 AI 앱의 replicas 및 CD 전환은 복구했다. 이 이력을 전체 수집 완료로 집계하지 않는다.

## FashionCLIP 벡터 적재 (2026-10-28)

`index_to_qdrant.py`/`indexer/entrypoint.py`(staging 직접 적재)를 대신해, 적재 가이드의
"임베딩은 S3에 먼저 기록 → 경량 importer → 버전 컬렉션 → 검증 후 alias 전환" 흐름으로 나눴다.
기존 `indexer/job.yaml`은 이전 실행용으로 남겨 두며 이번 실행에 쓰지 않는다.

| 단계 | 파일 | 하는 일 | Qdrant |
| --- | --- | --- | --- |
| 임베딩 | `indexer/embed_job.py`, `embed-job.yaml` | 승인본 재검증 → curated manifest SHA-256 대조 → S3 저장 이미지로 CPU 임베딩 → `pipeline/vector-runs/<id>/` | 접근 안 함 |
| 적재 | `indexer/import_job.py`, `import-job.yaml` | 벡터·payload 사전 검사 → 새 `fitzza_products_<version>` 생성·인덱스 → batch upsert → 검증 보고서 | 새 컬렉션만 |
| 전환 | `indexer/switch_alias.py` | 이전 대상 기록, 점 수 확인 후 단일 요청으로 alias 교체, 같은 명령으로 롤백 | alias만 |

계약:

- Point = 상품 + 색상(`color_raw.strip().lower()`) + 저장 이미지 S3 키, ID는 그 문자열의 UUIDv5.
- 이미지는 크롤링 때 S3에 받아 둔 `images/products/<id>/` 사본을 쓴다(manifest의 sha256 대조). 받지 못한 이미지는 `failures/planning.json`에 남기고 건너뛴다.
- 전처리·특징 추출은 recommendation-service `SearchEngine.encode_image`와 같다(CLIPProcessor → `get_image_features` → L2 정규화).
- 모델 revision은 운영 추천 서비스가 실제로 받은 커밋(HF 캐시 snapshot 디렉터리 이름)을 `--model-revision`으로 넘긴다. 다르면 질의 벡터와 상품 벡터가 어긋난다.
- payload: recommendation-service가 읽는 키(`product_id` 정수, `brand_name`, `color_normalized` 배열, `color_raw`, `subcategory`, `sizes` 등) + Qdrant 계약 키(`color_variant`, `normalized_color`, `brand`, `image_key`).
- 인덱스: `product_id`·`price` integer, `category`·`subcategory`·`color_normalized`·`normalized_color`·`color_variant`·`brand`·`brand_name` keyword.
- 이어하기: `plan.json`(데이터·모델 fingerprint)이 같을 때만 기존 part를 건너뛴다. part는 create-only로 쓴다. 다른 데이터·모델이면 새 `--vector-run-id`가 필요하다.
- importer는 벡터 차원·NaN·0벡터·payload 누락·모델 불일치·중복이 하나라도 있으면 Qdrant에 연결하기 전에 거부한다. 같은 이름의 컬렉션이 있으면 `--resume` 없이는 실패한다.
- `switch_alias.py`는 실제 컬렉션 이름을 alias로 쓰거나 alias를 대상으로 지정하면 거부한다. 컬렉션을 삭제하지 않는다.

이미지 빌드(빌드 컨텍스트는 `infra/data-pipeline`). 베이스(`BASE_IMAGE`)는 노드에서 실행 중인 recommendation-service
이미지 digest와 같아야 한다. 노드 디스크가 20GB라, 다른 베이스(3.4GB)를 받으면 디스크가 차서 Pod가 퇴거된다
(10/28 `fashion-clip-embed-20261025-01`이 이 이유로 이미지 압축 해제 중 `no space left on device`로 실패, 임베딩 미시작).
추천 서비스가 재배포되면 digest를 다시 확인한다.

```powershell
docker buildx build --platform linux/arm64 --provenance=false -f indexer/Dockerfile -t <repo>/fitzza/fashion-clip:vector-20261028-01 --push .
```

IAM(`fitzza-prod-indexer`, `indexer/policy.json`): 이번 실행의 승인본·curated manifest·저장 이미지 읽기,
이미지와 이번 vector run 경로 목록 조회, 이번 vector run 경로 읽기·쓰기만 허용한다.

검증: 가짜 S3 + 메모리 Qdrant 단위 테스트(`test_vector_run.py`), Qdrant 1.15.5 실서버에서 적재·인덱스 9개·검증 8항목·
`--resume`·alias 전환/거부/롤백 확인. 실제 모델 추론과 운영 데이터 적재는 별도 실행 승인 후 진행한다.
