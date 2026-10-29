package com.fitzza.user.domain;

// 사용자 역할. 가입하면 USER이고, 관리자는 운영에서 계정을 지정해 ADMIN으로 바꾼다(이슈 #225).
// Access Token의 role 클레임으로 실려 게이트웨이가 X-User-Role 헤더로 각 서비스에 넘긴다.
public enum UserRole {
    USER,
    ADMIN
}
