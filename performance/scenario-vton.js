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
const endpoint = `${baseUrl}/api/v1/vton`;
const photoId = readPositiveNumber('PHOTO_ID', undefined, true);
const productIds = readProductIds();

if (iterations < vus) {
  throw new Error('ITERATIONS must be at least VUS');
}

const acceptanceTime = new Trend('fitzza_vton_accept_ms', true);
const completionTime = new Trend('fitzza_vton_complete_ms', true);
const completionSuccess = new Rate('fitzza_vton_success');
const failureCount = new Counter('fitzza_vton_failures');
const timeoutCount = new Counter('fitzza_vton_timeouts');

export const options = {
  scenarios: {
    vton: {
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
    const fittingId = requestFitting(deadline);
    acceptanceTime.add(Date.now() - startedAt);

    waitForFitting(fittingId, deadline);
    completionTime.add(Date.now() - startedAt);
    succeeded = true;
  } catch (error) {
    timedOut = Date.now() >= deadline;
    const message = timedOut ? 'Job deadline exceeded' : error.message;
    console.error(`vton: ${message}`);
  } finally {
    completionSuccess.add(succeeded);
    if (!succeeded) {
      failureCount.add(1);
    }
    if (timedOut) {
      timeoutCount.add(1);
    }
    check(succeeded, {
      'vton completed successfully': value => value,
    });
  }
}

function requestFitting(deadline) {
  const response = http.post(
    endpoint,
    JSON.stringify({ photoId, productIds }),
    requestParams('POST', deadline),
  );
  ensureWithinDeadline(deadline);
  const accepted = parseResponse(response, 202);
  if (!accepted || !Number.isSafeInteger(accepted.fittingId)
      || accepted.fittingId <= 0 || accepted.status !== 'PENDING') {
    throw new Error('Invalid acceptance ID or status');
  }
  return accepted.fittingId;
}

function waitForFitting(fittingId, deadline) {
  while (Date.now() < deadline) {
    const response = http.get(`${endpoint}/${fittingId}`, requestParams('GET', deadline));
    ensureWithinDeadline(deadline);
    const result = parseResponse(response, 200);
    if (!result || result.fittingId !== fittingId) {
      throw new Error('Invalid result ID');
    }
    if (result.status === 'COMPLETED') {
      if (typeof result.resultImageUrl !== 'string' || !result.resultImageUrl.trim()) {
        throw new Error('Invalid completed result');
      }
      return;
    }
    if (result.status === 'FAILED') {
      throw new Error('Job failed');
    }
    if (result.status !== 'PENDING') {
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
    tags: { name: `${method} /api/v1/vton${method === 'GET' ? '/{id}' : ''}` },
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
  const thresholds = { fitzza_vton_success: ['rate>=0.95'] };
  if (__ENV.ACCEPT_P95_MS !== undefined) {
    const limit = readPositiveNumber('ACCEPT_P95_MS');
    thresholds.fitzza_vton_accept_ms = [`p(95)<${limit}`];
  }
  if (__ENV.COMPLETE_P95_MS !== undefined) {
    const limit = readPositiveNumber('COMPLETE_P95_MS');
    thresholds.fitzza_vton_complete_ms = [`p(95)<${limit}`];
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

function readProductIds() {
  const values = (__ENV.PRODUCT_IDS || '').split(',').map(value => Number(value.trim()));
  const validCount = values.length >= 2 && values.length <= 5;
  const validIds = values.every(value => Number.isSafeInteger(value) && value > 0);
  const uniqueIds = new Set(values).size === values.length;
  if (!validCount || !validIds || !uniqueIds) {
    throw new Error('PRODUCT_IDS must contain 2 to 5 distinct positive integers separated by commas');
  }
  return values;
}
