#!/usr/bin/env python3
"""FITZZA-179 Gateway 수용 스모크.

BASE_URL만 바꿔 로컬 Compose·EKS ALB에 같은 시나리오를 재실행한다.
토큰·비밀번호는 실행 시 환경 변수로만 받고, 로그에는 마스킹한다.

  BASE_URL=http://localhost:8080 \\
  SMOKE_EMAIL=... SMOKE_PASSWORD=... \\
  python3 scripts/acceptance_smoke.py

인증 성공·찜 쓰기 시나리오는 SMOKE_EMAIL/SMOKE_PASSWORD가 있을 때만 실행한다.
없으면 해당 시나리오는 SKIP으로 남기고, 나머지 실패 시 exit 1.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin

DEFAULT_TIMEOUT_SECONDS = 10
ALLOWED_ORIGIN = os.getenv("SMOKE_ALLOWED_ORIGIN", "https://app.fitzza.site")
DENIED_ORIGIN = "http://not-allowed.example"
TOKEN_RE = re.compile(r"(Bearer\s+)([A-Za-z0-9._\-]+)|(\"accessToken\"\s*:\s*\")([^\"]+)")


@dataclass(frozen=True)
class CheckResult:
    name: str
    status: str  # PASS | FAIL | SKIP
    detail: str


def mask_secrets(text: str, *extra: str) -> str:
    masked = TOKEN_RE.sub(
        lambda m: f"{m.group(1) or m.group(3)}***",
        text,
    )
    for secret in extra:
        if secret:
            masked = masked.replace(secret, "***")
    return masked


def _request(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    body: dict[str, Any] | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> tuple[int, dict[str, str], str]:
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Accept", "application/json")
    if body is not None:
        req.add_header("Content-Type", "application/json")
    for key, value in (headers or {}).items():
        req.add_header(key, value)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            return resp.status, {k.lower(): v for k, v in resp.headers.items()}, raw
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        return exc.code, {k.lower(): v for k, v in exc.headers.items()}, raw


def run_checks(base_url: str, email: str | None, password: str | None, timeout: float) -> list[CheckResult]:
    base = base_url.rstrip("/") + "/"
    results: list[CheckResult] = []

    # 1) health
    status, _, body = _request("GET", urljoin(base, "health"), timeout=timeout)
    ok = status == 200 and '"status":"UP"' in body.replace(" ", "")
    results.append(CheckResult(
        "health",
        "PASS" if ok else "FAIL",
        f"GET /health -> {status} body={mask_secrets(body)[:200]}",
    ))

    # 2) auth failure (wrong password or missing user)
    status, _, body = _request(
        "POST",
        urljoin(base, "api/auth/signin"),
        body={"email": "smoke-invalid@example.com", "password": "wrong-password"},
        timeout=timeout,
    )
    ok = status == 401
    results.append(CheckResult(
        "auth_fail",
        "PASS" if ok else "FAIL",
        f"POST /api/auth/signin (invalid) -> {status} (expect 401) body={mask_secrets(body)[:200]}",
    ))

    # 3) core read: products
    status, _, body = _request("GET", urljoin(base, "api/products?page=0&size=1"), timeout=timeout)
    ok = status == 200
    product_id: int | None = None
    if ok:
        try:
            payload = json.loads(body)
            items = payload.get("content") or payload.get("items") or payload
            if isinstance(items, list) and items:
                first = items[0]
                product_id = first.get("productId") or first.get("id")
        except json.JSONDecodeError:
            ok = False
    results.append(CheckResult(
        "products_list",
        "PASS" if ok else "FAIL",
        f"GET /api/products -> {status} productId={product_id}",
    ))

    # 4) CORS allow / deny (preflight-like Origin on real API)
    status, headers, _ = _request(
        "OPTIONS",
        urljoin(base, "api/auth/refresh"),
        headers={
            "Origin": ALLOWED_ORIGIN,
            "Access-Control-Request-Method": "POST",
        },
        timeout=timeout,
    )
    allow_origin = headers.get("access-control-allow-origin", "")
    # ALB/Gateway may answer 200 or 204 for OPTIONS; require allow-origin match.
    cors_ok = status in (200, 204) and allow_origin == ALLOWED_ORIGIN
    results.append(CheckResult(
        "cors_allow",
        "PASS" if cors_ok else "FAIL",
        f"OPTIONS /api/auth/refresh Origin={ALLOWED_ORIGIN} -> {status} ACO={allow_origin}",
    ))

    status, headers, _ = _request(
        "OPTIONS",
        urljoin(base, "api/auth/refresh"),
        headers={
            "Origin": DENIED_ORIGIN,
            "Access-Control-Request-Method": "POST",
        },
        timeout=timeout,
    )
    allow_origin = headers.get("access-control-allow-origin", "")
    deny_ok = status == 403 or (allow_origin != DENIED_ORIGIN and allow_origin != "*")
    results.append(CheckResult(
        "cors_deny",
        "PASS" if deny_ok else "FAIL",
        f"OPTIONS /api/auth/refresh Origin={DENIED_ORIGIN} -> {status} ACO={allow_origin or '-'}",
    ))

    # 5) auth success + wishlist write/read/cleanup (optional credentials)
    if not email or not password:
        results.append(CheckResult(
            "auth_success_wishlist",
            "SKIP",
            "SMOKE_EMAIL/SMOKE_PASSWORD 미설정 — 인증 성공·찜 쓰기 시나리오 생략",
        ))
        return results

    status, headers, body = _request(
        "POST",
        urljoin(base, "api/auth/signin"),
        body={"email": email, "password": password},
        timeout=timeout,
    )
    access = ""
    if status == 200:
        try:
            access = json.loads(body).get("accessToken") or ""
        except json.JSONDecodeError:
            access = ""
    auth_ok = status == 200 and bool(access)
    results.append(CheckResult(
        "auth_success",
        "PASS" if auth_ok else "FAIL",
        f"POST /api/auth/signin -> {status} token={'***' if access else '-'}",
    ))
    if not auth_ok or product_id is None:
        results.append(CheckResult(
            "wishlist_flow",
            "SKIP" if auth_ok and product_id is None else "FAIL",
            "로그인 실패 또는 상품 목록이 비어 찜 시나리오 중단",
        ))
        return results

    auth_header = {"Authorization": f"Bearer {access}"}
    status, _, body = _request(
        "POST",
        urljoin(base, "api/wishlists"),
        headers=auth_header,
        body={"itemId": int(product_id)},
        timeout=timeout,
    )
    add_ok = status == 200
    results.append(CheckResult(
        "wishlist_add",
        "PASS" if add_ok else "FAIL",
        mask_secrets(f"POST /api/wishlists itemId={product_id} -> {status} {body[:120]}", password, access),
    ))

    status, _, body = _request(
        "GET",
        urljoin(base, "api/wishlists?page=0&size=5"),
        headers=auth_header,
        timeout=timeout,
    )
    list_ok = status == 200
    results.append(CheckResult(
        "wishlist_list",
        "PASS" if list_ok else "FAIL",
        mask_secrets(f"GET /api/wishlists -> {status}", password, access),
    ))

    status, _, body = _request(
        "DELETE",
        urljoin(base, f"api/wishlists?itemId={int(product_id)}"),
        headers=auth_header,
        timeout=timeout,
    )
    del_ok = status == 204
    results.append(CheckResult(
        "wishlist_cleanup",
        "PASS" if del_ok else "FAIL",
        mask_secrets(f"DELETE /api/wishlists itemId={product_id} -> {status} (expect 204)", password, access),
    ))
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=os.getenv("BASE_URL", ""), help="Gateway base URL")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    args = parser.parse_args(argv)
    if not args.base_url:
        print("BASE_URL or --base-url is required", file=sys.stderr)
        return 2

    email = os.getenv("SMOKE_EMAIL") or None
    password = os.getenv("SMOKE_PASSWORD") or None
    results = run_checks(args.base_url, email, password, args.timeout)
    failed = 0
    for item in results:
        print(f"[{item.status}] {item.name}: {mask_secrets(item.detail, password or '')}")
        if item.status == "FAIL":
            failed += 1
    if failed:
        print(f"acceptance smoke failed: {failed} check(s)", file=sys.stderr)
        return 1
    print("acceptance smoke passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
