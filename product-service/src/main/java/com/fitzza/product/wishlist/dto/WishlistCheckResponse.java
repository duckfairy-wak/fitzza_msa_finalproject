package com.fitzza.product.wishlist.dto;

import io.swagger.v3.oas.annotations.media.Schema;

@Schema(description = "찜 소유 확인 결과")
public record WishlistCheckResponse(
        @Schema(description = "사용자가 해당 항목을 찜했는지 여부") boolean wishlisted) {
}
