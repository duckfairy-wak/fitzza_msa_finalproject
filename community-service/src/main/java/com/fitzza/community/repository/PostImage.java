package com.fitzza.community.repository;

import com.fitzza.community.domain.VoteItemType;
import java.util.List;
import java.util.Map;
import java.util.function.Function;
import java.util.stream.Collectors;

// 목록 한 페이지의 글마다 썸네일 후보 이미지를 한 번에 가져오기 위한 조회 결과.
// 상품 선택지면 itemId(상품 ID)로 지금 쓸 수 있는 이미지 주소를 다시 받는다.
public record PostImage(Long postId, String imageUrl, VoteItemType itemType, String itemId) {

    public PostImage(Long postId, String imageUrl) {
        this(postId, imageUrl, null, null);
    }

    // 상품 선택지의 상품 ID. 코디 선택지이거나 숫자가 아니면 null이다.
    public Long productId() {
        if (itemType != VoteItemType.PRODUCT || itemId == null) {
            return null;
        }
        try {
            return Long.valueOf(itemId);
        } catch (NumberFormatException exception) {
            return null;
        }
    }

    public static Map<Long, String> toMap(List<PostImage> images) {
        return images.stream()
                .collect(Collectors.toMap(PostImage::postId, PostImage::imageUrl, (first, second) -> first));
    }

    public static Map<Long, PostImage> byPostId(List<PostImage> images) {
        return images.stream()
                .collect(Collectors.toMap(PostImage::postId, Function.identity(), (first, second) -> first));
    }
}
