import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const JOB_ID = 7;
const REQUEST_DURATION_MS = 5;
const DEFAULT_ENVIRONMENT = {
  ACCESS_TOKEN: 'mock-only',
  PHOTO_ID: '1',
  PRODUCT_IDS: '101,201',
  WAIT_TIMEOUT_SECONDS: '1',
  POLL_INTERVAL_SECONDS: '0.1',
};

function createResponse(status, body, invalidJson) {
  return {
    status,
    json() {
      if (invalidJson) {
        throw new Error('Invalid JSON');
      }
      return body;
    },
  };
}

function createResultBody(service, mode, pollCount) {
  const isVton = service === 'vton';
  const idField = isVton ? 'fittingId' : 'requestId';
  const body = {
    [idField]: mode === 'wrong_id' ? JOB_ID + 1 : JOB_ID,
    status: isVton ? 'COMPLETED' : 'DONE',
    items: [],
    combos: [],
    resultImageUrl: 'https://example.test/image.png',
  };

  if (mode === 'timeout' || pollCount === 1) {
    body.status = isVton ? 'PENDING' : 'PROCESSING';
  }
  if (mode === 'failed') {
    body.status = 'FAILED';
  }
  if (mode === 'unknown') {
    body.status = 'UNKNOWN';
  }
  if (mode === 'missing_result') {
    delete body[isVton ? 'resultImageUrl' : 'items'];
  }
  return body;
}

function simulate(service, mode, overrides = {}, execution = {}) {
  let now = 0;
  let polls = 0;
  const metrics = new Map();
  const calls = [];
  const isVton = service === 'vton';
  const idField = isVton ? 'fittingId' : 'requestId';
  const pending = isVton ? 'PENDING' : 'PROCESSING';

  class Metric {
    constructor(name) {
      this.values = [];
      metrics.set(name, this.values);
    }

    add(value) {
      this.values.push(value);
    }
  }

  const context = vm.createContext({
    __ENV: { ...DEFAULT_ENVIRONMENT, ...overrides },
    __VU: execution.vu || 1,
    __ITER: execution.iteration || 0,
    Date: { now: () => now },
    console: { error() {} },
    Trend: Metric,
    Rate: Metric,
    Counter: Metric,
    sleep(seconds) {
      now += seconds * 1000;
    },
    check(value, checks) {
      return Object.values(checks).every(validate => validate(value));
    },
    http: {
      post(url, payload, params) {
        calls.push({ url, payload: JSON.parse(payload), params });
        now += REQUEST_DURATION_MS;
        const status = mode === 'post_error' ? 503 : 202;
        const body = {
          [idField]: mode === 'bad_acceptance' ? null : JOB_ID,
          status: pending,
        };
        return createResponse(status, body, mode === 'bad_json');
      },
      get(url, params) {
        calls.push({ url, params });
        polls++;
        now += mode === 'http_timeout' ? params.timeout : REQUEST_DURATION_MS;
        const body = createResultBody(service, mode, polls);
        const httpFailed = mode === 'http_error' || mode === 'http_timeout';
        return createResponse(httpFailed ? 503 : 200, body, mode === 'bad_json');
      },
    },
  });
  const entry = readFileSync(new URL(`../scenario-${service}.js`, import.meta.url), 'utf8');
  const source = entry.replace(/^import .*;\r?$/gm, '')
    .replace(/export default function/g, 'function execute')
    .replace(/export /g, '');
  vm.runInContext(`${source}\nglobalThis.scenarioOptions = options;`, context);
  const runCount = execution.runCount || 1;
  for (let index = 0; index < runCount; index++) {
    context.__ITER = (execution.iteration || 0) + index;
    vm.runInContext('execute();', context);
  }
  return { metrics, calls, options: context.scenarioOptions };
}

const OUTCOMES = [
  { mode: 'success', name: '완료 성공', succeeded: true, accepted: true },
  { mode: 'failed', name: '작업 실패', accepted: true },
  { mode: 'unknown', name: '알 수 없는 상태', accepted: true },
  { mode: 'timeout', name: '폴링 대기 제한 초과', accepted: true, timedOut: true },
  { mode: 'http_timeout', name: 'HTTP 요청 중 대기 제한 초과', accepted: true, timedOut: true },
  { mode: 'post_error', name: '접수 HTTP 오류' },
  { mode: 'bad_acceptance', name: '접수 ID 누락' },
  { mode: 'http_error', name: '조회 HTTP 오류', accepted: true },
  { mode: 'bad_json', name: '잘못된 JSON' },
  { mode: 'wrong_id', name: '조회 ID 불일치', accepted: true },
  { mode: 'missing_result', name: '완료 결과 누락', accepted: true },
];

function assertMetrics(service, metrics, outcome) {
  const metric = suffix => metrics.get(`fitzza_${service}_${suffix}`);
  const succeeded = Boolean(outcome.succeeded);
  assert.deepEqual(metric('success'), [succeeded]);
  assert.equal(metric('complete_ms').length, Number(succeeded));
  assert.equal(metric('accept_ms').length, Number(Boolean(outcome.accepted)));
  assert.equal(metric('failures').at(-1), Number(!succeeded));
  assert.equal(metric('timeouts').at(-1), Number(Boolean(outcome.timedOut)));
}

function assertRequests(service, calls) {
  const firstRequest = calls[0];
  const path = service === 'vton' ? 'vton' : 'recommendations';
  assert.equal(firstRequest.params.headers.Authorization, 'Bearer mock-only');
  assert.equal(firstRequest.url, `http://localhost:8080/api/v1/${path}`);
  if (service === 'vton') {
    assert.equal(JSON.stringify(firstRequest.payload), '{"photoId":1,"productIds":[101,201]}');
  } else {
    assert.ok(firstRequest.payload.query);
  }
  assert.ok(calls.every(call => call.params.timeout > 0 && call.params.timeout <= 1000));
  assert.ok(calls.every(call => !call.params.tags.name.includes(`/${JOB_ID}`)));
}

for (const service of ['recommendation', 'vton']) {
  for (const outcome of OUTCOMES) {
    test(`${service}: ${outcome.name}`, () => {
      const { mode } = outcome;
      const { metrics, calls, options } = simulate(service, mode);
      assertMetrics(service, metrics, outcome);
      assertRequests(service, calls);
      assert.equal(options.scenarios[service].maxDuration, '61s');
    });
  }
}

const INVALID_SETTINGS = [
  { name: '토큰 누락', values: { ACCESS_TOKEN: '' } },
  { name: '인증정보가 포함된 URL', values: { BASE_URL: 'http://user:pass@localhost' } },
  { name: 'VU 0명', values: { VUS: '0' } },
  { name: '반복 횟수 0회', values: { ITERATIONS: '0' } },
  { name: 'VU보다 적은 반복 횟수', values: { VUS: '2', ITERATIONS: '1' } },
  { name: '숫자가 아닌 폴링 간격', values: { POLL_INTERVAL_SECONDS: 'NaN' } },
  { name: '음수 대기 제한', values: { WAIT_TIMEOUT_SECONDS: '-1' } },
  { name: 'HTTP 제한 0초', values: { HTTP_TIMEOUT_SECONDS: '0' } },
  { name: '접수 p95 기준 0', values: { ACCEPT_P95_MS: '0' } },
  { name: '숫자가 아닌 완료 p95 기준', values: { COMPLETE_P95_MS: 'no' } },
  { name: '사진 ID 누락', values: { PHOTO_ID: '' } },
  { name: '중복 상품 ID', values: { PRODUCT_IDS: '1,1' } },
  { name: '상품 1개', values: { PRODUCT_IDS: '1' } },
  { name: '상품 6개', values: { PRODUCT_IDS: '1,2,3,4,5,6' } },
  { name: '음수 상품 ID', values: { PRODUCT_IDS: '1,-2' } },
];

for (const { name, values: settings } of INVALID_SETTINGS) {
  test(`잘못된 설정 거부: ${name}`, () => {
    assert.throws(() => simulate('vton', 'success', settings));
  });
}

test('공백으로만 구성된 추천 질의 거부', () => {
  assert.throws(() => simulate('recommendation', 'success', { QUERY: ' ' }));
});

test('사용자 지정 p95 기준과 반복 횟수에 따른 실행 제한 설정', () => {
  const { options } = simulate('recommendation', 'success', {
    VUS: '2',
    ITERATIONS: '5',
    ACCEPT_P95_MS: '500',
    COMPLETE_P95_MS: '2000',
  });
  assert.equal(options.scenarios.recommendation.maxDuration, '183s');
  assert.equal(options.thresholds.fitzza_recommendation_accept_ms[0], 'p(95)<500');
  assert.equal(options.thresholds.fitzza_recommendation_complete_ms[0], 'p(95)<2000');
});

test('추천 요청마다 원래 질의를 유지하면서 고유 문자열 추가', () => {
  const query = '주말 코디 추천';
  const { calls } = simulate('recommendation', 'success', { QUERY: query }, { runCount: 3 });
  const queries = calls.filter(call => call.payload).map(call => call.payload.query);

  assert.equal(queries.length, 3);
  assert.equal(new Set(queries).size, 3);
  for (const requestQuery of queries) {
    assert.ok(requestQuery.startsWith(`${query}\n[k6:`));
    assert.match(requestQuery.slice(query.length), /^\n\[k6:[a-z0-9]+-1-[0-2]-[a-z0-9]+\]$/);
  }
});

test('같은 시각에 실행한 VU와 재실행 간 추천 질의 구분', () => {
  const queryFor = vu => simulate('recommendation', 'success', {}, { vu }).calls[0].payload.query;
  const firstVuQuery = queryFor(1);
  const secondVuQuery = queryFor(2);
  const rerunQuery = queryFor(1);

  assert.notEqual(firstVuQuery, secondVuQuery);
  assert.notEqual(firstVuQuery, rerunQuery);
});
