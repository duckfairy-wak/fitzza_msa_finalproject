package com.fitzza.community.dto;

import com.fitzza.community.domain.Comment;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;

public record CommentCreateRequest(
        @NotBlank(message = "댓글 내용을 입력해주세요.")
                @Size(max = Comment.CONTENT_MAX_LENGTH, message = "댓글은 500자 이하로 입력해주세요.")
                String content,
        Long parentCommentId) {
}
