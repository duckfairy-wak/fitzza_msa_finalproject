/**
 * 구매 여정 k6 시나리오 (FITZZA-296)
 *
 * 회원가입 → 로그인 → 상품 목록 → 상품 상세 → 장바구니 추가 → 주문 생성 → 주문 상세
 *
 * GET 조회 부하(api.js)와 달리 쓰기(담기·주문)를 포함한다. 기본은 스모크(VU 1 / 1회).
 *
 * 예:
 *   k6 run -e BASE_URL=http://localhost:8080 -e VUS=1 -e ITERATIONS=1 performance/purchase_flow.js
 *   k6 run -e BASE_URL=https://api.fitzza.site -e VUS=1 -e ITERATIONS=1 performance/purchase_flow.js
 *
 * PR #242 k6 컨테이너가 있으면:
 *   docker compose run --rm --entrypoint k6 k6 run -e BASE_URL=http://gateway-service:8080 -e VUS=1 -e ITERATIONS=1 /scripts/purchase_flow.js
 */

import http from 'k6/http';
import { check, fail, group, sleep } from 'k6';
import { Trend } from 'k6/metrics';

function readBaseUrl() {
  const baseUrl = (__ENV.BASE_URL || 'http://localhost:8080').replace(/\/$/, '');
  const originPattern = /^https?:\/\/[a-zA-Z0-9.-]+(?::[0-9]{1,5})?$/;
  if (!originPattern.test(baseUrl)) {
    throw new Error('BASE_URL must be an HTTP(S) origin without credentials or a path');
  }
  return baseUrl;
}

const baseUrl = readBaseUrl();
// FE·#242 api.js 와 같이 /api/v1 기본. Swagger 경로면 API_PREFIX=/api
const apiPrefix = __ENV.API_PREFIX || '/api/v1';
const vus = Number(__ENV.VUS || 1);
const iterations = Number(__ENV.ITERATIONS || 1);
const fetchImage = String(__ENV.FETCH_IMAGE || 'false').toLowerCase() === 'true';
const fixedProductId = __ENV.PRODUCT_ID ? Number(__ENV.PRODUCT_ID) : null;
const password = __ENV.PASSWORD || 'fitzza12';

const productDetailTrend = new Trend('fitzza_product_detail_ms', true);
const cartAddTrend = new Trend('fitzza_cart_add_ms', true);
const orderCreateTrend = new Trend('fitzza_order_create_ms', true);
const imageGetTrend = new Trend('fitzza_presigned_image_ms', true);

export const options = {
  scenarios: {
    purchase_smoke: {
      executor: 'shared-iterations',
      vus,
      iterations,
      maxDuration: __ENV.MAX_DURATION || '3m',
    },
  },
  thresholds: {
    checks: ['rate>0.95'],
    http_req_failed: ['rate<0.05'],
    fitzza_product_detail_ms: ['p(95)<3000'],
    fitzza_cart_add_ms: ['p(95)<3000'],
    fitzza_order_create_ms: ['p(95)<5000'],
  },
};

function jsonHeaders(token) {
  const headers = {
    'Content-Type': 'application/json',
    Accept: 'application/json',
    'User-Agent': 'fitzza-k6-purchase',
  };
  if (token) {
    headers.Authorization = `Bearer ${token}`;
  }
  return headers;
}

function requireOk(res, name, okStatuses) {
  const allowed = okStatuses || [200];
  const ok = check(res, {
    [`${name} status`]: (r) => allowed.includes(r.status),
  });
  if (!ok) {
    fail(`${name} failed: status=${res.status} body=${String(res.body).slice(0, 300)}`);
  }
}

function uniqueIdentity() {
  const stamp = `${Date.now()}`.slice(-6);
  const nick = `k${__VU}${__ITER}${stamp}`.slice(0, 10);
  const email = `k6u${__VU}i${__ITER}${stamp}@fitzza.test`;
  return { email, nickname: nick };
}

function signupAndSignin() {
  const identity = uniqueIdentity();

  return group('auth', () => {
    const signupRes = http.post(
      `${baseUrl}${apiPrefix}/auth/signup`,
      JSON.stringify({
        email: identity.email,
        password,
        nickname: identity.nickname,
      }),
      { headers: jsonHeaders(), tags: { name: 'POST /auth/signup' } },
    );
    requireOk(signupRes, 'signup', [201]);

    const signinRes = http.post(
      `${baseUrl}${apiPrefix}/auth/signin`,
      JSON.stringify({ email: identity.email, password }),
      { headers: jsonHeaders(), tags: { name: 'POST /auth/signin' } },
    );
    requireOk(signinRes, 'signin', [200]);
    const body = signinRes.json();
    if (!body || !body.accessToken) {
      fail('signin response missing accessToken');
    }
    return body.accessToken;
  });
}

function pickProductId(token) {
  if (fixedProductId) {
    return fixedProductId;
  }
  const listRes = http.get(`${baseUrl}${apiPrefix}/products?page=0&size=5&sort=TIME_DESC`, {
    headers: jsonHeaders(token),
    tags: { name: 'GET /products' },
  });
  requireOk(listRes, 'product list', [200]);
  const page = listRes.json();
  const content = page && page.content;
  if (!content || content.length === 0) {
    fail('product list empty — seed products first');
  }
  return content[0].productId;
}

function loadProductDetail(token, productId) {
  const started = Date.now();
  const res = http.get(`${baseUrl}${apiPrefix}/products/${productId}`, {
    headers: jsonHeaders(token),
    tags: { name: 'GET /products/{id}' },
  });
  productDetailTrend.add(Date.now() - started);
  requireOk(res, 'product detail', [200]);
  const detail = res.json();
  if (!detail || !detail.options || detail.options.length === 0) {
    fail(`product ${productId} has no options`);
  }

  if (fetchImage) {
    const imageUrl = detail.thumbnailUrl || (detail.images && detail.images[0]);
    if (imageUrl && /^https?:\/\//i.test(imageUrl)) {
      const imgStarted = Date.now();
      const imgRes = http.get(imageUrl, {
        tags: { name: 'GET presigned-image' },
        redirects: 5,
      });
      imageGetTrend.add(Date.now() - imgStarted);
      check(imgRes, {
        'presigned image status 200': (r) => r.status === 200,
      });
    }
  }

  return detail.options[0].optionId;
}

function addToCart(token, optionId) {
  const started = Date.now();
  const res = http.post(
    `${baseUrl}${apiPrefix}/carts`,
    JSON.stringify({ optionId, quantity: 1 }),
    { headers: jsonHeaders(token), tags: { name: 'POST /carts' } },
  );
  cartAddTrend.add(Date.now() - started);
  requireOk(res, 'cart add', [201]);
  const body = res.json();
  if (!body || body.cartId == null) {
    fail('cart add missing cartId');
  }
  return body.cartId;
}

function createOrder(token, cartId) {
  const started = Date.now();
  const res = http.post(
    `${baseUrl}${apiPrefix}/orders`,
    JSON.stringify({
      cartIds: [cartId],
      recipientName: 'k6tester',
      recipientPhone: '010-1234-5678',
      shippingAddress: '서울특별시 강남구 테헤란로 1 101동 101호',
    }),
    { headers: jsonHeaders(token), tags: { name: 'POST /orders' } },
  );
  orderCreateTrend.add(Date.now() - started);
  requireOk(res, 'order create', [201]);
  const body = res.json();
  if (!body || body.orderId == null) {
    fail('order create missing orderId');
  }
  return body.orderId;
}

function getOrder(token, orderId) {
  const res = http.get(`${baseUrl}${apiPrefix}/orders/${orderId}`, {
    headers: jsonHeaders(token),
    tags: { name: 'GET /orders/{id}' },
  });
  requireOk(res, 'order detail', [200]);
}

export default function () {
  const token = signupAndSignin();

  let productId;
  let optionId;
  let cartId;
  let orderId;

  group('product', () => {
    productId = pickProductId(token);
    optionId = loadProductDetail(token, productId);
  });

  group('cart', () => {
    cartId = addToCart(token, optionId);
  });

  group('order', () => {
    orderId = createOrder(token, cartId);
    getOrder(token, orderId);
  });

  sleep(Number(__ENV.THINK_TIME || 0.3));
}
