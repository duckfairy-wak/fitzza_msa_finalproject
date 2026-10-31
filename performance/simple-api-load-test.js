import http from 'k6/http';
import { check, sleep } from 'k6';
import exec from 'k6/execution';

function readPositiveInteger(name, fallback, maximum) {
  const value = __ENV[name] || fallback;
  if (!/^[1-9][0-9]*$/.test(value) || Number(value) > maximum) {
    throw new Error(`${name} must be an integer from 1 to ${maximum}`);
  }
  return Number(value);
}

function readBaseUrl() {
  const baseUrl = (__ENV.BASE_URL || '').replace(/\/$/, '');
  const originPattern = /^https?:\/\/[a-zA-Z0-9.-]+(?::[0-9]{1,5})?$/;

  if (!originPattern.test(baseUrl)) {
    throw new Error('BASE_URL must be an HTTP(S) origin without credentials or a path');
  }
  return baseUrl;
}

function readProfile() {
  const profile = __ENV.PROFILE || 'public';
  if (!['public', 'member', 'all'].includes(profile)) {
    throw new Error('PROFILE must be public, member or all');
  }
  return profile;
}

const baseUrl = readBaseUrl();
const profile = readProfile();
const token = __ENV.ACCESS_TOKEN || '';
if (profile !== 'public' && !token) {
  throw new Error('ACCESS_TOKEN is required for member/all');
}

const virtualUsers = readPositiveInteger('VUS', '5', 50);
const durationSeconds = readPositiveInteger('DURATION_SECONDS', '60', 600);
const p95LimitMs = readPositiveInteger('P95_MS', '1000', 30000);

function isPageResponse(body) {
  return body !== null && Array.isArray(body.content);
}

function isProfileResponse(body) {
  return body !== null && typeof body.email === 'string';
}

const publicEndpoints = [
  {
    name: 'products',
    path: '/api/v1/products?page=0&size=20',
    valid: isPageResponse,
  },
  {
    name: 'categories',
    path: '/api/v1/categories',
    valid: Array.isArray
  },
  {
    name: 'community_feed',
    path: '/api/v1/community/posts?page=0&size=20',
    valid: isPageResponse,
  },
];

const memberEndpoints = [
  {
    name: 'my_profile',
    path: '/api/v1/users/me',
    valid: isProfileResponse
  },
  {
    name: 'cart',
    path: '/api/v1/carts',
    valid: Array.isArray
  },
  {
    name: 'orders',
    path: '/api/v1/orders?page=0&size=20',
    valid: isPageResponse,
  },
  {
    name: 'notifications',
    path: '/api/v1/notifications?page=0&size=20',
    valid: isPageResponse,
  },
];

const endpointsByProfile = {
  public: publicEndpoints,
  member: memberEndpoints,
  all: [...publicEndpoints, ...memberEndpoints],
};
const endpoints = endpointsByProfile[profile];

function createThresholds() {
  const thresholds = {};

  for (const endpoint of endpoints) {
    const selector = `{endpoint:${endpoint.name},scenario:api}`;
    thresholds[`http_req_duration${selector}`] = [`p(95)<${p95LimitMs}`];
    thresholds[`http_req_failed${selector}`] = [
      {
        threshold: 'rate<0.01',
        abortOnFail: true,
        delayAbortEval: '10s',
      },
    ];
    thresholds[`checks${selector}`] = ['rate>0.99'];
    thresholds[`http_reqs${selector}`] = ['count>0'];
  }

  return thresholds;
}

export const options = {
  scenarios: {
    api: {
      executor: 'ramping-vus',
      startVUs: 0,
      stages: [
        { duration: '10s', target: virtualUsers },
        { duration: `${durationSeconds}s`, target: virtualUsers },
        { duration: '10s', target: 0 },
      ],
      gracefulRampDown: '15s',
      gracefulStop: '15s',
    },
  },
  thresholds: createThresholds(),
  summaryTrendStats: ['avg', 'min', 'med', 'max', 'p(90)', 'p(95)', 'p(99)'],
  systemTags: ['status', 'method', 'name', 'scenario', 'expected_response'],
};

function requestEndpoint(endpoint) {
  const headers = {
    Accept: 'application/json',
    'User-Agent': 'fitzza-k6-api',
  };
  if (profile !== 'public') {
    headers.Authorization = `Bearer ${token}`;
  }

  return http.get(`${baseUrl}${endpoint.path}`, {
    headers,
    tags: { name: endpoint.name, endpoint: endpoint.name },
    timeout: '10s',
    redirects: 0,
  });
}

function isValidResponse(response, endpoint) {
  if (response.status !== 200) {
    return false;
  }

  try {
    return endpoint.valid(response.json());
  } catch (_) {
    return false;
  }
}

export function setup() {
  for (const endpoint of endpoints) {
    const response = requestEndpoint(endpoint);
    if (!isValidResponse(response, endpoint)) {
      exec.test.abort(`Preflight failed: ${endpoint.name}, status=${response.status}; expected 200 and API JSON`);
    }
  }
}

export default function testApiEndpoints() {
  for (const endpoint of endpoints) {
    const response = requestEndpoint(endpoint);
    check(
      response,
      {
        [`${endpoint.name}: HTTP 200 and API JSON`]: (result) => isValidResponse(result, endpoint),
      },
      { endpoint: endpoint.name },
    );
    sleep(1);
  }
}

export function handleSummary(data) {
  const rows = ['# k6 API performance', '', '| Metric / threshold | Result |', '| --- | --- |'];
  for (const [name, metric] of Object.entries(data.metrics)) {
    for (const [threshold, result] of Object.entries(metric.thresholds || {})) {
      const verdict = result.ok ? 'PASS' : 'FAIL';
      rows.push(`| ${name}: ${threshold} | ${verdict} |`);
    }
  }
  const summary = `${rows.join('\n')}\n`;
  return {
    'summary.json': JSON.stringify(data, null, 2),
    stdout: summary,
  };
}
