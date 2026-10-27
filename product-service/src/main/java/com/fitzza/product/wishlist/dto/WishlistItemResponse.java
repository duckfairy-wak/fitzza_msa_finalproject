package com.fitzza.product.wishlist.dto;

import com.fitzza.product.product.entity.ProductEntity;
import com.fitzza.product.wishlist.entity.WishlistEntity;
import io.swagger.v3.oas.annotations.media.Schema;
import java.time.Instant;
import java.util.function.UnaryOperator;

@Schema(description = "찜 목록 항목")
public record WishlistItemResponse(
        @Schema(description = "찜 ID", example = "1") Long wishlistId,
        @Schema(description = "상품 ID", example = "1") Long itemId,
        @Schema(description = "브랜드명", example = "Fitzza") String brandName,
        @Schema(description = "상품명", example = "오버핏 코튼 셔츠") String name,
        @Schema(description = "가격(원)", example = "39000") Integer price,
        @Schema(description = "대표 이미지 URL. S3 object key면 Presigned GET URL") String imageUrl,
        @Schema(description = "대분류 카테고리 코드", example = "001") String categoryL1,
        @Schema(description = "찜한 일시") Instant createdAt) {

    public static WishlistItemResponse of(
            WishlistEntity wishlist, ProductEntity product, UnaryOperator<String> resolveImageUrl) {
        return new WishlistItemResponse(
                wishlist.getWishlistId(),
                Long.valueOf(wishlist.getItemId()),
                product == null || product.getBrand() == null ? null : product.getBrand().getBrandName(),
                product == null ? null : product.getProductName(),
                product == null ? null : product.getPrice(),
                product == null ? null : resolveImageUrl.apply(product.getImageUrl()),
                product == null ? null : product.getCategory1(),
                wishlist.getCreatedAt());
    }
}
