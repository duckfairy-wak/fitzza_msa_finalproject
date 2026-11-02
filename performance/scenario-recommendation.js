import http from 'k6/http';
import { check, sleep } from 'k6';
import { Counter, Rate, Trend } from 'k6/metrics';

const baseUrl = readBaseUrl();
const accessToken = readAccessToken();
const vus = readPositiveNumber('VUS', 1, true);
const iterations = readPositiveNumber('ITERATIONS', 1, true);
const pollIntervalSeconds = readPositiveNumber('POLL_INTERVAL_SECONDS', 2);
const waitTimeoutSeconds = readPositiveNumber('WAIT_TIMEOUT_SECONDS', 600);
const httpTimeoutSeconds = readPositiveNumber('HTTP_TIMEOUT_SECONDS', 30);
const endpoint = `${baseUrl}/api/v1/recommendations`;
const query = readQuery();

if (iterations < vus) {
  throw new Error('ITERATIONS must be at least VUS');
}

const acceptanceTime = new Trend('fitzza_recommendation_accept_ms', true);
const completionTime = new Trend('fitzza_recommendation_complete_ms', true);
const completionSuccess = new Rate('fitzza_recommendation_success');
const failureCount = new Counter('fitzza_recommendation_failures');
const timeoutCount = new Counter('fitzza_recommendation_timeouts');

export const options = {
  scenarios: {
    recommendation: {
      executor: 'shared-iterations',
      vus,
      iterations,
      maxDuration: `${Math.ceil(iterations / vus) * (waitTimeoutSeconds + 60)}s`,
    },
  },
  thresholds: buildThresholds(),
  summaryTrendStats: ['avg', 'min', 'med', 'max', 'p(90)', 'p(95)', 'p(99)'],
  systemTags: ['status', 'method', 'name', 'scenario', 'expected_response', 'error_code'],
};

export default function () {
  const startedAt = Date.now();
  const deadline = startedAt + waitTimeoutSeconds * 1000;
  let succeeded = false;
  let timedOut = false;

  failureCount.add(0);
  timeoutCount.add(0);

  try {
    const requestId = requestRecommendation(deadline);
    acceptanceTime.add(Date.now() - startedAt);

    waitForRecommendation(requestId, deadline);
    completionTime.add(Date.now() - startedAt);
    succeeded = true;
  } catch (error) {
    timedOut = Date.now() >= deadline;
    const message = timedOut ? 'Job deadline exceeded' : error.message;
    console.error(`recommendation: ${message}`);
  } finally {
    completionSuccess.add(succeeded);
    if (!succeeded) {
      failureCount.add(1);
    }
    if (timedOut) {
      timeoutCount.add(1);
    }
    check(succeeded, {
      'recommendation completed successfully': value => value,
    });
  }
}

function requestRecommendation(deadline) {
  const requestQuery = createRequestQuery();
  const response = http.post(
    endpoint,
    JSON.stringify({ query: requestQuery }),
    requestParams('POST', deadline),
  );
  ensureWithinDeadline(deadline);
  const accepted = parseResponse(response, 202);
  if (!accepted || !Number.isSafeInteger(accepted.requestId)
      || accepted.requestId <= 0 || accepted.status !== 'PROCESSING') {
    throw new Error('Invalid acceptance ID or status');
  }
  return accepted.requestId;
}

function createRequestQuery() {
  const timestamp = Date.now().toString(36);
  const vu = __VU.toString(36);
  const iteration = __ITER.toString(36);
  const random = Math.random().toString(36).slice(2, 8);
  return `${query}\n[k6:${timestamp}-${vu}-${iteration}-${random}]`;
}

function waitForRecommendation(requestId, deadline) {
  while (Date.now() < deadline) {
    const response = http.get(`${endpoint}/${requestId}`, requestParams('GET', deadline));
    ensureWithinDeadline(deadline);
    const result = parseResponse(response, 200);
    if (!result || result.requestId !== requestId) {
      throw new Error('Invalid result ID');
    }
    if (result.status === 'DONE') {
      if (!Array.isArray(result.items) || !Array.isArray(result.combos)) {
        throw new Error('Invalid completed result');
      }
      return;
    }
    if (result.status === 'FAILED') {
      throw new Error('Job failed');
    }
    if (result.status !== 'PROCESSING') {
      throw new Error('Invalid job status');
    }
    const remainingSeconds = Math.max(0, (deadline - Date.now()) / 1000);
    sleep(Math.min(pollIntervalSeconds, remainingSeconds));
  }
  throw new Error('Job deadline exceeded');
}

function requestParams(method, deadline) {
  const remainingMilliseconds = deadline - Date.now();
  return {
    headers: {
      Authorization: `Bearer ${accessToken}`,
      'Content-Type': 'application/json',
      Accept: 'application/json',
    },
    tags: { name: `${method} /api/v1/recommendations${method === 'GET' ? '/{id}' : ''}` },
    timeout: Math.max(1, Math.min(httpTimeoutSeconds * 1000, remainingMilliseconds)),
    redirects: 0,
  };
}

function parseResponse(response, expectedStatus) {
  if (response.status !== expectedStatus) {
    throw new Error(`Unexpected HTTP status ${response.status}`);
  }
  try {
    return response.json();
  } catch (_) {
    throw new Error('Invalid JSON response');
  }
}

function ensureWithinDeadline(deadline) {
  if (Date.now() >= deadline) {
    throw new Error('Job deadline exceeded');
  }
}

function buildThresholds() {
  const thresholds = { fitzza_recommendation_success: ['rate>=0.95'] };
  if (__ENV.ACCEPT_P95_MS !== undefined) {
    const limit = readPositiveNumber('ACCEPT_P95_MS');
    thresholds.fitzza_recommendation_accept_ms = [`p(95)<${limit}`];
  }
  if (__ENV.COMPLETE_P95_MS !== undefined) {
    const limit = readPositiveNumber('COMPLETE_P95_MS');
    thresholds.fitzza_recommendation_complete_ms = [`p(95)<${limit}`];
  }
  return thresholds;
}

function readPositiveNumber(name, fallback, integer = false) {
  const value = Number(__ENV[name] === undefined ? fallback : __ENV[name]);
  if (!Number.isFinite(value) || value <= 0 || (integer && !Number.isSafeInteger(value))) {
    throw new Error(`${name} must be a positive ${integer ? 'integer' : 'number'}`);
  }
  return value;
}

function readBaseUrl() {
  const value = (__ENV.BASE_URL || 'http://localhost:8080').replace(/\/$/, '');
  if (!/^https?:\/\/[a-zA-Z0-9.-]+(?::[0-9]{1,5})?$/.test(value)) {
    throw new Error('BASE_URL must be an HTTP(S) origin without credentials or a path');
  }
  return value;
}

function readAccessToken() {
  const value = (__ENV.ACCESS_TOKEN || '').trim();
  if (!value || /^Bearer\s/i.test(value)) {
    throw new Error('ACCESS_TOKEN is required without Bearer prefix');
  }
  return value;
}

function readQuery() {
  const defaultQuery = '주말 나들이에 어울리는 캐주얼 코디를 추천해주세요.';
  const value = (__ENV.QUERY === undefined ? defaultQuery : __ENV.QUERY).trim();
  if (!value) {
    throw new Error('QUERY must not be blank');
  }
  return value;
}
