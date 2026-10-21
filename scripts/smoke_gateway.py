"""Gateway 라우팅·인증·CORS·오류 응답 확인(FITZZA-168).

Gateway 주소 하나만 받아 외부에서 보이는 동작만 확인한다. 로컬(docker compose)과 배포 환경(ALB) 모두에 쓸 수 있다.
표준 라이브러리만 쓴다. 토큰·쿠키 값은 출력하지 않는다.

    python3 scripts/smoke_gateway.py --base-url http://localhost:8080 --origin http://localhost:5173

--read-only를 주면 회원가입·로그인·재발급·로그아웃(테스트 계정을 새로 만듦)을 건너뛴다.
테스트 계정은 smoke-<시각>@fitzza.test로 만들며, 회원 탈퇴 API가 없어 지워지지 않는다.
실패가 하나라도 있으면 종료 코드 1로 끝난다.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field

DISALLOWED_ORIGIN = "https://not-allowed.example.com"


@dataclass
class Response:
    status: int
    headers: dict[str, list[str]]
    body: object

    def header(self, name: str) -> str | None:
        values = self.headers.get(name.lower())
        return values[0] if values else None


@dataclass
class Checker:
    base_url: str
    timeout: float
    failures: list[str] = field(default_factory=list)

    def call(self, method: str, path: str, *, body=None, headers=None) -> Response:
        data = json.dumps(body).encode("utf-8") if body is not None else None
        request = urllib.request.Request(self.base_url + path, data=data, method=method)
        if data is not None:
            request.add_header("Content-Type", "application/json")
        for name, value in (headers or {}).items():
            request.add_header(name, value)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return Response(response.status, _headers(response.headers), _json(response.read()))
        except urllib.error.HTTPError as error:
            return Response(error.code, _headers(error.headers), _json(error.read()))
        except (urllib.error.URLError, TimeoutError) as error:
            return Response(0, {}, {"error": type(error).__name__})

    def check(self, name: str, expected, actual) -> bool:
        ok = expected == actual
        print(f"{'OK  ' if ok else 'FAIL'} {name} | 기대: {expected} | 실제: {actual}")
        if not ok:
            self.failures.append(name)
        return ok


def _headers(message) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for name, value in message.items():
        result.setdefault(name.lower(), []).append(value)
    return result


def _json(raw: bytes):
    if not raw:
        return None
    try:
        return json.loads(raw)
    except ValueError:
        return None


def _code(response: Response):
    return response.body.get("code") if isinstance(response.body, dict) else None


def _error_shape(response: Response) -> bool:
    body = response.body
    return isinstance(body, dict) and set(body) >= {"status", "code", "message"} and body["status"] == response.status


def _refresh_cookie(response: Response) -> str | None:
    for value in response.headers.get("set-cookie", []):
        first = value.split(";", 1)[0]
        name, _, cookie = first.partition("=")
        if name.strip() == "refreshToken" and cookie:
            return first.strip()
    return None


def _cookie_attributes(response: Response) -> set[str]:
    for value in response.headers.get("set-cookie", []):
        if value.startswith("refreshToken="):
            return {part.strip().split("=", 1)[0].lower() for part in value.split(";")[1:]}
    return set()


def check_health_and_routes(c: Checker) -> None:
    c.check("1. GET /health", 200, c.call("GET", "/health").status)
    for path in ("/api/products?page=0&size=1", "/api/v1/products?page=0&size=1"):
        c.check(f"2. 상품 목록 라우팅 {path.split('?')[0]}", 200, c.call("GET", path).status)
    for path in ("/api/community/posts?page=0&size=1", "/api/v1/community/posts?page=0&size=1"):
        c.check(f"3. 커뮤니티 목록 라우팅 {path.split('?')[0]}", 200, c.call("GET", path).status)
    reviews = c.call("GET", "/api/v1/reviews?productId=1&page=0&size=1")
    c.check("4. 리뷰 목록 라우팅 /api/v1/reviews", 200, reviews.status)
    c.check("5. 없는 주소는 404", 404, c.call("GET", "/api/v1/not-a-route").status)
    # X-Request-Id는 서비스로 넘기는 요청에 붙는다(Gateway 자체 /health에는 없음). 보낸 값은 그대로 이어진다.
    routed = c.call("GET", "/api/v1/products?page=0&size=1")
    c.check("6. 라우팅된 응답에 X-Request-Id", True, bool(routed.header("X-Request-Id")))
    given = "smoke-request-id-0001"
    echoed = c.call("GET", "/api/v1/products?page=0&size=1", headers={"X-Request-Id": given})
    c.check("6-1. 보낸 X-Request-Id를 그대로 이어감", given, echoed.header("X-Request-Id"))


def check_auth_errors(c: Checker) -> None:
    no_token = c.call("GET", "/api/v1/users/me")
    c.check("7. 토큰 없이 내 정보 401 UNAUTHENTICATED", (401, "UNAUTHENTICATED"), (no_token.status, _code(no_token)))
    c.check("7-1. 오류 응답 형식 {status, code, message}", True, _error_shape(no_token))
    spoofed = c.call("GET", "/api/v1/users/me", headers={"X-User-Id": "1"})
    c.check("8. X-User-Id만 보내면 401 (헤더 위조 차단)", (401, "UNAUTHENTICATED"), (spoofed.status, _code(spoofed)))
    garbage = c.call("GET", "/api/v1/users/me", headers={"Authorization": "Bearer not-a-jwt"})
    c.check("9. 잘못된 토큰 401 INVALID_TOKEN", (401, "INVALID_TOKEN"), (garbage.status, _code(garbage)))
    c.check("9-1. 오류 응답 형식 {status, code, message}", True, _error_shape(garbage))
    recommendation = c.call("GET", "/api/v1/recommendations/history")
    c.check("10. 추천은 비로그인 401", 401, recommendation.status)


def check_cors(c: Checker, origin: str) -> None:
    preflight_headers = {"Origin": origin, "Access-Control-Request-Method": "POST"}
    allowed = c.call("OPTIONS", "/api/v1/auth/refresh", headers=preflight_headers)
    c.check(
        "11. 허용 origin preflight 200 + Allow-Origin·Allow-Credentials",
        (200, origin, "true"),
        (allowed.status, allowed.header("Access-Control-Allow-Origin"), allowed.header("Access-Control-Allow-Credentials")),
    )
    denied = c.call(
        "OPTIONS", "/api/v1/auth/refresh", headers={**preflight_headers, "Origin": DISALLOWED_ORIGIN})
    c.check(
        "12. 허용하지 않은 origin preflight 403, Allow-Origin 없음",
        (403, None),
        (denied.status, denied.header("Access-Control-Allow-Origin")),
    )
    simple = c.call("GET", "/api/v1/products?page=0&size=1", headers={"Origin": origin})
    exposed = (simple.header("Access-Control-Expose-Headers") or "").lower()
    c.check(
        "13. 허용 origin 요청에 Allow-Origin + X-Request-Id 노출",
        (origin, True),
        (simple.header("Access-Control-Allow-Origin"), "x-request-id" in exposed),
    )


def check_auth_flow(c: Checker) -> None:
    stamp = time.strftime("%m%d%H%M%S")
    email = f"smoke-{stamp}@fitzza.test"
    password = f"Smoke{stamp}a"
    signup = c.call("POST", "/api/v1/auth/signup",
                    body={"email": email, "password": password, "nickname": f"gw{stamp[-8:]}"})
    if not c.check("14. 회원가입", 201, signup.status):
        return
    signin = c.call("POST", "/api/v1/auth/signin", body={"email": email, "password": password})
    access = signin.body.get("accessToken") if isinstance(signin.body, dict) else None
    cookie = _refresh_cookie(signin)
    c.check("15. 로그인 200 + accessToken + refreshToken 쿠키", (200, True, True),
            (signin.status, bool(access), bool(cookie)))
    c.check("15-1. refreshToken 쿠키 HttpOnly", True, "httponly" in _cookie_attributes(signin))
    if not (access and cookie):
        return
    me = c.call("GET", "/api/v1/users/me", headers={"Authorization": f"Bearer {access}"})
    c.check("16. 토큰으로 내 정보 200 (Gateway → user-service)", (200, email),
            (me.status, me.body.get("email") if isinstance(me.body, dict) else None))
    refreshed = c.call("POST", "/api/v1/auth/refresh", headers={"Cookie": cookie})
    new_access = refreshed.body.get("accessToken") if isinstance(refreshed.body, dict) else None
    new_cookie = _refresh_cookie(refreshed)
    c.check("17. 쿠키로 재발급 200 + 새 쿠키", (200, True, True),
            (refreshed.status, bool(new_access), bool(new_cookie) and new_cookie != cookie))
    reused = c.call("POST", "/api/v1/auth/refresh", headers={"Cookie": cookie})
    c.check("18. 이미 쓴 Refresh Token 재사용 401", 401, reused.status)
    if not (new_access and new_cookie):
        return
    signout = c.call("POST", "/api/v1/auth/signout",
                     headers={"Cookie": new_cookie, "Authorization": f"Bearer {new_access}"})
    c.check("19. 로그아웃 200", 200, signout.status)
    after = c.call("GET", "/api/v1/users/me", headers={"Authorization": f"Bearer {new_access}"})
    c.check("20. 로그아웃한 Access Token 401 INVALID_TOKEN", (401, "INVALID_TOKEN"), (after.status, _code(after)))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-url", default="http://localhost:8080", help="Gateway 주소(끝에 / 없이)")
    parser.add_argument("--origin", default="http://localhost:5173", help="CORS 허용 목록에 있는 FE 주소")
    parser.add_argument("--timeout", type=float, default=10.0, help="요청 하나의 제한 시간(초)")
    parser.add_argument("--read-only", action="store_true", help="계정을 만드는 인증 흐름(14~20)을 건너뜀")
    args = parser.parse_args()

    checker = Checker(args.base_url.rstrip("/"), args.timeout)
    health = checker.call("GET", "/health")
    if health.status == 0:
        print(f"Gateway({checker.base_url})에 연결하지 못했습니다: {health.body}")
        return 1
    check_health_and_routes(checker)
    check_auth_errors(checker)
    check_cors(checker, args.origin)
    if not args.read_only:
        check_auth_flow(checker)
    if checker.failures:
        print(f"\n실패 {len(checker.failures)}건: {', '.join(checker.failures)}")
        return 1
    print("\n모두 통과")
    return 0


if __name__ == "__main__":
    sys.exit(main())
