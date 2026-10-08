package com.fitzza.community.dto;

import com.fitzza.community.domain.Post;
import com.fitzza.community.domain.PostCategory;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Size;

public record PostCreateRequest(
        @NotBlank(message = "제목을 입력해주세요.")
                @Size(max = Post.TITLE_MAX_LENGTH, message = "제목은 100자 이하로 입력해주세요.")
                String title,
        @NotBlank(message = "내용을 입력해주세요.")
                @Size(max = Post.CONTENT_MAX_LENGTH, message = "내용은 5000자 이하로 입력해주세요.")
                String content,
        @NotNull(message = "분류를 선택해주세요.") PostCategory category,
        @Size(max = Post.IMAGE_URL_MAX_LENGTH, message = "이미지 주소가 너무 깁니다.") String imageUrl) {
}
