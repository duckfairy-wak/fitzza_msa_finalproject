package com.fitzza.community.dto;

// 회원 서비스에서 닉네임을 받지 못하면 nickname은 null이다.
public record AuthorResponse(Long userId, String nickname) {
}
