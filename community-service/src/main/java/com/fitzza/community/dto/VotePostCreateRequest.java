package com.fitzza.community.dto;

import com.fitzza.community.domain.Post;
import com.fitzza.community.domain.PostCategory;
import com.fitzza.community.domain.VoteOption;
import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Size;
import java.util.List;

public record VotePostCreateRequest(
        @NotBlank(message = "제목을 입력해주세요.")
                @Size(max = Post.TITLE_MAX_LENGTH, message = "제목은 100자 이하로 입력해주세요.")
                String title,
        @NotBlank(message = "내용을 입력해주세요.")
                @Size(max = Post.CONTENT_MAX_LENGTH, message = "내용은 5000자 이하로 입력해주세요.")
                String content,
        @NotNull(message = "분류를 선택해주세요.") PostCategory category,
        @NotNull(message = "투표 선택지는 2~4개여야 합니다.")
                @Size(
                        min = VoteOption.MIN_OPTIONS,
                        max = VoteOption.MAX_OPTIONS,
                        message = "투표 선택지는 2~4개여야 합니다.")
                List<@NotNull(message = "투표 선택지를 확인해주세요.") @Valid VoteOptionRequest> options) {
}
