package com.fitzza.product.wishlist.dto;

import com.fitzza.product.wishlist.entity.WishlistEntity;
import io.swagger.v3.oas.annotations.media.Schema;

@Schema(description = "찜 추가 결과")
public record WishlistResponse(
        @Schema(description = "찜 ID", example = "1") Long wishlistId) {

    public static WishlistResponse from(WishlistEntity wishlist) {
        return new WishlistResponse(wishlist.getWishlistId());
    }
}
