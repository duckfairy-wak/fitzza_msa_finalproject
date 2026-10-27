# 프런트 배포 준비 (FITZZA-220)

2026-10-22 첫 배포를 완료했고, 2026-10-27 완료 조건을 다시 검증했다.

## 프런트 소스 기준

- 기본 저장소: https://github.com/GledoubleN/fitzza-frontend
- 확인 브랜치: `dev` (기존 저장소/development 기준을 대체).
- 2026-10-22 확인 커밋: `3762ec420748598ea9e3824ec32e939b7f34d9ff`.
- 배포 전 승인된 태그 또는 고정 커밋을 사용한다. 움직이는 dev HEAD를 자동 배포하지 않는다.
- 공통 axios `withCredentials: true` 적용을 확인했다.
- 운영 빌드 입력은 `.env.example`을 참고하며 프런트 `.env.example`의 mocking=true를 운영에 복사하지 않는다.

## 생성한 리소스

- S3: `fitzza-prod-frontend-414901227428` (`ap-northeast-2`)
- 퍼블릭 액세스 차단 4개 활성화, SSE-S3 AES256, 버전 관리 활성화.
- `bucket-policy.json`은 비 TLS 접근을 거부하고 아래 CloudFront 배포에만 객체 읽기를 허용한다.
- ACM: `arn:aws:acm:us-east-1:414901227428:certificate/edc6796d-0d2b-42e2-8490-a9a05dd6d127`
- 인증서 도메인: `app.fitzza.site`, DNS 검증 및 발급 완료 (`ISSUED`).
- CloudFront: `E267AOIW0VV48R`, `dxvpgq7jw5349.cloudfront.net`
- OAC: `EF45ZR5EQKHAF`
- Free 구독: `arn:aws:pricingplanmanager::414901227428:subscription:sub_3L1sTArpMGir05W6ehYEDVyMSOx`, `ACTIVE` 확인.
- 포함 WAF: `CreatedByCloudFront-864dc702` (추가 유료 보호 기능 미선택).
- `distribution-config.json`: 적용한 설정. 업데이트 시 현재 ETag와 설정을 다시 조회해 비교해야 한다.
- HTTPS 리다이렉트, TLS 1.2 이상, 기본 객체 index.html, 403/404 → index.html(200).
- 기본 경로는 관리형 CachingDisabled, `/assets/*`는 CachingOptimized를 사용한다.
  UseOriginCacheControlHeaders는 방문자 Host를 S3로 전달해 404가 발생하므로 사용하지 않는다.
- Free 플랜에서 제공하지 않는 액세스 로그/사용자 지정 보안 헤더는 활성화하지 않았다.

## 가비아 DNS 검증

유형: `CNAME`

- 이름: `_ab012117cdde154e06b5f52b11d3fad5.app.fitzza.site.`
- 값: `_c717f72375b7acca081862dc3f6522a4.wzccmgtwzk.acm-validations.aws.`

가비아가 `fitzza.site`를 자동으로 붙이면 호스트에는
`_ab012117cdde154e06b5f52b11d3fad5.app`만 입력한다. 발급 후에도 갱신을 위해 유지한다.

## 별도 후속 항목

- 성공 로그인·세션 유지·로그아웃 검증은 테스트 계정이 필요하다.
- 프런트 의존성 경고와 브라우저 `animation` 오류는 프런트 팀에서 별도로 추적한다.

## 첫 배포 기록 (2026-10-22)

- 소스: GledoubleN/fitzza-frontend dev, 고정 SHA `3762ec420748598ea9e3824ec32e939b7f34d9ff`.
- Node 24.15.0 / npm 11.12.1, `npm ci --ignore-scripts` 및 `npm run build` 성공.
- index JS `index-DNDz5jhj.js`, CSS `index-vod1GPti.css`.
- assets는 `public,max-age=31536000,immutable`, 나머지는 `no-cache`로 게시.
  mockServiceWorker.js는 제외했으며 기존 assets 삭제 없음.
- 무효화: `I2A1F8K92D9F8XM4I6S2NV8J6P`, Completed 확인.
- delivery 스택은 기존 템플릿 유지, FrontendOrigin만 `https://app.fitzza.site`로 전환.
  변경 계획의 역할/파이프라인 표시는 동일 참조 재계산임을 Before/After 비교로 확인.
- ConfigMap 동일 반영 후 Gateway만 재시작. 다른 앱 이미지·Qdrant·Redis 변경 없음.
- 스모크 기본 허용 origin은 운영 주소. 로컬 검증은 `SMOKE_ALLOWED_ORIGIN`으로 재정의한다.
- npm audit: 전체 high 7개, 운영 의존성 high 5개(전이 항목 포함).
  grpc/follow-redirects Node 경로 경고이며 브라우저 번들에서 해당 패키지 문자열은 미검출.
  보안 무결성 보장은 아니며 프런트 담당자의 잠금파일/의존성 점검 필요. 자동 fix 미실행.
- 최초 배포라 이전 프런트 릴리스가 없다. 이후 롤백은 검증된 고정 SHA를 별도 폴더에
  빌드해 같은 캐시 정책으로 재업로드하고 무효화한다. 이번에 롤백 실증까지 한 것은 아니다.
- 최종 확인: CloudFront Deployed, Free ACTIVE, `/`·`/categories`·JS assets 200.
  브라우저 카테고리 이동/직접 새로고침 렌더링 확인.
- API 수용 smoke: health/인증 실패/상품 목록/CORS 허용·거부 5개 PASS,
  성공 로그인·찜 쓰기는 계정 미제공으로 SKIP. 로그인 유지·로그아웃·FCM 미검증.
- 브라우저 로그에서 `Cannot use 'in' operator to search for 'animation' in undefined`
  오류 관찰. 상세 발생 조건은 프런트 팀 확인 필요하며 전체 UI 정상으로 간주하지 않는다.

## 완료 조건 재검증 (2026-10-27)

- CloudFront `E267AOIW0VV48R` 상태 `Deployed`, 진행 중 무효화 0건 확인.
- `https://app.fitzza.site/`와 `/categories`가 유효한 TLS 인증서로 200 응답.
- S3 Block Public Access 4개 항목 활성화, 버킷 정책 `IsPublic=false`, 직접 `index.html`
  요청 403 확인.
- OAC `EF45ZR5EQKHAF`, ACM 인증서, 포함 WAF Web ACL 연결 상태 확인.
- WAF 관리형 Common Rule Set의 XSS 쿼리 샘플이 `BLOCK`으로 기록된 것을 확인했다.
  CloudFront의 SPA용 403 오류 응답이 `index.html` 200으로 변환되므로 외부 상태 코드만으로
  차단 여부를 판정하지 않고 WAF sampled requests와 `BlockedRequests` 지표를 사용한다.
- Free 플랜 제약과 기존 비용 승인 범위에 따라 별도 WAF 전체 요청 로그 대상은 만들지 않았다.
  보안 확인은 암호화된 유료 로그 저장소 대신 WAF sampled requests와 CloudWatch 지표로 수행한다.
- S3 버전 관리 `Enabled`, `index.html` 현재 버전 ID, 완료된 캐시 무효화 기록을 확인했다.
  롤백은 아래 절차처럼 검증된 고정 SHA를 재빌드·재업로드한 뒤 무효화한다.

콘솔에서 Free $0/month를 선택해 생성하고 API로 FREE/ACTIVE를 확인했다.
유료 WAF나 유료 플랜 자동 전환은 승인되지 않았다.
Free 불가 시 WAF 없는 종량제 비용을 검토하고 별도 확인한다.

## 운영·롤백 절차

1. 배포 전 승인된 프런트 태그 또는 고정 SHA와 운영 환경 변수를 기록한다.
2. 해당 소스를 별도 디렉터리에서 빌드하고 `assets/*`에는 immutable 캐시,
   `index.html` 등 진입 파일에는 `no-cache`를 적용해 업로드한다.
3. CloudFront 무효화를 생성하고 `Completed`까지 확인한다.
4. `/`, 직접 라우트, 정적 asset, CORS 허용·거부 스모크를 실행한다.
5. 실패하면 직전 검증 SHA를 같은 방식으로 재빌드·재업로드하고 다시 무효화한다.
6. S3 직접 접근 403, WAF sampled requests와 `BlockedRequests`, CloudFront 상태를 재확인한다.

전체 인프라가 무료인 것은 아니다. S3 저장/요청 및 기존 백엔드 비용은 별도다.
