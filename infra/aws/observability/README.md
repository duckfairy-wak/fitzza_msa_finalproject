# FITZZA-176 기본 운영·비용 감시

이 문서는 FITZZA-176의 초기 인벤토리와 비용 승인 범위 안에서 운영 감시를
확장하기 위한 기준이다. 2026-10-27(KST) 현재 계정과 리전에 실제로 존재하는
구성을 먼저 확인했으며, 임계값·수신자·payer 권한이 확정되기 전에는 알람이나
대시보드를 생성하지 않는다.

## 확인 범위

- AWS 계정: linked account `414901227428`
- 애플리케이션 리전: `ap-northeast-2`
- 비용 API 리전: `us-east-1`
- 확인 시각: 2026-10-27 15:38 KST
- 확인 방법: CloudWatch alarms/dashboards/log groups, Budgets, Cost Explorer 읽기 전용 조회

## 현재 인벤토리

| 영역 | 확인 결과 | 운영 의미 |
| --- | --- | --- |
| CloudWatch metric alarms | 0개 | 오류·큐 적체·노드 포화에 대한 자동 알림 없음 |
| CloudWatch dashboards | 0개 | 운영자가 한 화면에서 상태를 확인할 기준 화면 없음 |
| `/aws/codebuild/fitzza-prod-build` | 보존 7일 | 파이프라인 실패 조사 가능 |
| `/aws/codebuild/fitzza-prod-deploy` | 보존 7일 | 배포 실패 조사 가능 |
| `/aws/lambda/fitzza-prod-node-scaler` | 보존 14일 | 스케일러 실행 조사 가능 |
| `/aws/eks/fitzza-prod/cluster` | 현재 `Never Expire`(보존 기간 미설정) | 목표 보존 기간: 미정(운영·비용 승인 필요) |
| EKS cluster log stored bytes | `1,922,623,851` bytes (CLI raw value) | 삭제·압축·보존 정책을 임의 적용하지 않고 승인 필요 |
| Budgets / Cost Explorer | linked account 권한 거부 | payer 관리자에게서 FITZZA-221 Budget·비용 조회 증적을 받아야 함 |

Payer 소유 Budget을 조회·설정하거나 linked account 필터를 포함한 집계 비용을
조회하려면 payer 권한이 필요하다. 현재 linked account 자격으로 실행한
`DescribeBudgets`와 `GetCostAndUsage`는 권한 거부되었으므로, FITZZA-221에 기록된
예산 요청안(USD 124, 50/80/100% 알림, 자동 조치 없음)을 기준으로 payer 관리자의
설정 결과를 별도 증적으로 받아야 한다.

## FITZZA-177 대시보드 초안

알람 상태 행을 최상단에 두고, 다음 최소 패널을 한 화면에 구성한다.

1. EKS 노드 CPU·메모리·Pod 수
2. 서비스별 5xx/error 로그 수와 배포 실패 수
3. VTON SQS visible messages, oldest message age, DLQ message count
4. RDS 연결/CPU·스토리지 여유와 NAT 처리량·시간
5. CloudFront 요청·4xx/5xx·WAF 차단 샘플 및 관련 링크
6. 현재 알람 상태와 마지막 배포 커밋

현재 알람·대시보드가 없으므로 실제 위젯을 저장하기 전 각 패널의 metric namespace,
dimension, 기간, 비용 영향을 확인한다. 대시보드 저장은 무료 범위와 공유 권한을
확인한 뒤 진행한다.

## FITZZA-178 알림 초안

임계값은 운영 기준선과 수신자를 확인한 뒤 확정한다. 우선순위는 다음과 같다.

- 서비스 5xx 또는 인증 실패 급증
- SQS 작업 큐 적체·DLQ 유입·오래된 메시지
- EKS 노드 CPU/메모리 포화와 Pod 재시작
- RDS 연결 고갈·스토리지 부족
- NAT/EC2·EBS·CloudFront 비용 신호와 Budget 초과 통지

오류 수처럼 데이터가 없으면 정상인 지표는 `notBreaching`, heartbeat/health 지표는
`breaching` 등 누락 데이터 처리를 명시한다. latency는 평균이 아니라 p90/p99를
사용하고, 일반 알람은 1분 주기·M-of-N 평가를 기본 후보로 삼되 실제 기준선 검증
전에는 생성하지 않는다.

## 다음 실행 순서

1. payer 관리자에게 FITZZA-221 Budget 생성·알림 전달·현재 누적 비용 증적 요청
2. 애플리케이션 운영자가 대시보드 수신자, 알림 채널, 각 임계값과 대응 시간을 승인
3. EKS cluster log 보존 기간과 암호화·접근 권한을 결정
4. 승인된 최소 대시보드(FITZZA-177)부터 생성하고 렌더링 확인
5. 승인된 알람(FITZZA-178)을 기존 이름 충돌 확인 후 생성
6. 알람 전환·복구, 누락 데이터, 비용 알림 전달을 테스트하고 Jira에 증적 기록

유료 로그 수집, 상세 Grafana 고도화, Budget Action·자동 종료는 별도 승인 없이는
추가하지 않는다.
