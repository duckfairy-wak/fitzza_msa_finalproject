package com.fitzza.community.dto;

import com.fitzza.community.domain.VoteItemType;
import com.fitzza.community.domain.VoteOption;
import com.fitzza.community.domain.VoteOptionSource;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Size;

// 직접 올린 사진(UPLOAD·IMAGE)은 itemId 없이 보낸다.
public record VoteOptionRequest(
        @NotNull(message = "선택지 출처를 골라주세요.") VoteOptionSource source,
        @NotNull(message = "선택지 종류를 골라주세요.") VoteItemType itemType,
        @Size(max = VoteOption.ITEM_ID_MAX_LENGTH, message = "선택지 대상 ID가 너무 깁니다.") String itemId,
        @NotBlank(message = "선택지 이미지를 넣어주세요.")
                @Size(max = VoteOption.IMAGE_URL_MAX_LENGTH, message = "이미지 주소가 너무 깁니다.")
                String imageUrl) {
}
