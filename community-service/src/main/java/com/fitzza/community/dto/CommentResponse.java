package com.fitzza.community.dto;

import com.fasterxml.jackson.annotation.JsonProperty;
import java.time.Instant;
import java.util.List;

// 삭제된 댓글은 답글이 남아 있을 때만 내려가며, 그때 내용은 안내 문구로 바뀌고 author는 null이다.
public record CommentResponse(
        Long commentId,
        String content,
        AuthorResponse author,
        long likeCount,
        boolean liked,
        @JsonProperty("isDeleted") boolean deleted,
        Instant createdAt,
        List<CommentResponse> replies) {
}
