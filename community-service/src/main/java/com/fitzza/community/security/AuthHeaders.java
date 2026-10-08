package com.fitzza.community.security;

public final class AuthHeaders {

    // 게이트웨이가 토큰을 검증한 뒤 붙여 주는 헤더. 서비스는 이 값으로만 사용자를 식별한다.
    public static final String USER_ID = "X-User-Id";

    private AuthHeaders() {
    }
}
