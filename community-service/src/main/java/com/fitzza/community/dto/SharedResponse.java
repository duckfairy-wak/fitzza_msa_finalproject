package com.fitzza.community.dto;

import com.fitzza.community.domain.Post;
import com.fitzza.community.domain.SharedItem;
import com.fitzza.community.domain.SharedSnapshot;
import com.fitzza.community.domain.SharedType;
import java.util.List;

// 공유 글의 공유 대상. snapshot과 items는 공유한 순간의 모습이다.
// WORLDCUP: snapshot에 우승 상품(productId·brandName·productName·price·imageUrl), items는 빈 목록.
// COMBO: snapshot에 총 가격(price)·첫 상품 이미지(imageUrl)·조화도 요약(summary), items에 코디 상품들.
// FITTING: snapshot에 결과 이미지(imageUrl), items에 입어 본 상품들.
// PRODUCT: snapshot에 찜한 상품(productId·brandName·productName·price·imageUrl), items는 빈 목록.
// 상품 이미지는 공유 당시 주소가 만료되므로 보여줄 때 새로 받은 주소(latest)로 바꾼다. 피팅 결과 이미지는 그대로 둔다.
public record SharedResponse(SharedType type, Long id, Snapshot snapshot, List<Item> items) {

    public static SharedResponse of(Post post) {
        return of(post, LatestImageUrls.NONE);
    }

    public static SharedResponse of(Post post, LatestImageUrls latest) {
        if (!post.isShared()) {
            return null;
        }
        SharedSnapshot snapshot = post.getSharedSnapshot();
        return new SharedResponse(
                post.getSharedType(),
                post.getSharedId(),
                snapshot == null
                        ? null
                        : new Snapshot(
                                snapshot.getProductId(),
                                snapshot.getBrandName(),
                                snapshot.getProductName(),
                                snapshot.getPrice(),
                                latest.pick(snapshotProductIdOf(post), snapshot.getImageUrl()),
                                snapshot.getSummary()),
                post.getSharedItems().stream().map(item -> Item.from(item, latest)).toList());
    }

    // 스냅샷 이미지가 어느 상품의 이미지인지. 월드컵·상품은 스냅샷 상품, 코디는 첫 상품이다.
    // 피팅은 결과 사진이라 상품 이미지가 아니므로 null이다.
    public static Long snapshotProductIdOf(Post post) {
        if (!post.isShared() || post.getSharedType() == null) {
            return null;
        }
        return switch (post.getSharedType()) {
            case WORLDCUP, PRODUCT -> post.getSharedSnapshot() == null ? null : post.getSharedSnapshot().getProductId();
            case COMBO -> post.getSharedItems().isEmpty() ? null : post.getSharedItems().get(0).getProductId();
            case FITTING -> null;
        };
    }

    public record Snapshot(
            Long productId, String brandName, String productName, Integer price, String imageUrl, String summary) {
    }

    public record Item(Long productId, String productName, Integer price, String imageUrl) {

        static Item from(SharedItem item, LatestImageUrls latest) {
            return new Item(
                    item.getProductId(),
                    item.getProductName(),
                    item.getPrice(),
                    latest.pick(item.getProductId(), item.getImageUrl()));
        }
    }
}
