package com.fitzza.community.dto;

import com.fitzza.community.domain.VoteItemType;
import com.fitzza.community.domain.VoteOption;
import com.fitzza.community.domain.VoteOptionSource;

public record VoteOptionResponse(
        Long voteOptionId,
        String label,
        VoteOptionSource source,
        VoteItemType itemType,
        Long itemId,
        String imageUrl,
        String name,
        Integer price) {

    public static VoteOptionResponse from(VoteOption option) {
        return from(option, LatestImageUrls.NONE);
    }

    // 상품 선택지는 저장된 이미지 주소가 만료되므로 새로 받은 주소로 바꾼다. 코디 선택지는 그대로 둔다.
    public static VoteOptionResponse from(VoteOption option, LatestImageUrls latest) {
        return new VoteOptionResponse(
                option.getId(),
                option.getLabel(),
                option.getSource(),
                option.getItemType(),
                toLongOrNull(option.getItemId()),
                latest.pick(productIdOf(option), option.getImageUrl()),
                option.getSnapshotName(),
                option.getSnapshotPrice());
    }

    public static Long productIdOf(VoteOption option) {
        return option.getItemType() == VoteItemType.PRODUCT ? toLongOrNull(option.getItemId()) : null;
    }

    // 저장은 문자열이다. 숫자 ID만 받기 전에 저장된 값이 숫자가 아니면 null로 내보낸다.
    private static Long toLongOrNull(String itemId) {
        if (itemId == null) {
            return null;
        }
        try {
            return Long.valueOf(itemId);
        } catch (NumberFormatException exception) {
            return null;
        }
    }
}
