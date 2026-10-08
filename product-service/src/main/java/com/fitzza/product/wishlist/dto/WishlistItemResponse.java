package com.fitzza.product.wishlist.dto;

import com.fitzza.product.product.entity.ProductEntity;
import com.fitzza.product.wishlist.entity.WishlistEntity;
import io.swagger.v3.oas.annotations.media.Schema;
import java.time.LocalDateTime;

@Schema(description = "찜 목록 항목")
public record WishlistItemResponse(
        @Schema(description = "찜 ID", example = "1") Long wishlistId,
        @Schema(description = "상품 ID", example = "1") String itemId,
        @Schema(description = "상품명", example = "오버핏 코튼 셔츠") String name,
        @Schema(description = "가격(원)", example = "39000") Integer price,
        @Schema(description = "대표 이미지 URL") String imageUrl,
        @Schema(description = "대분류 카테고리 코드", example = "001") String categoryL1,
        @Schema(description = "찜한 일시") LocalDateTime createdAt) {

    public static WishlistItemResponse of(WishlistEntity wishlist, ProductEntity product) {
        return new WishlistItemResponse(
                wishlist.getWishlistId(),
                wishlist.getItemId(),
                product == null ? null : product.getProductName(),
                product == null ? null : product.getPrice(),
                product == null ? null : product.getImageUrl(),
                product == null ? null : product.getCategory1(),
                wishlist.getCreatedAt());
    }
}
