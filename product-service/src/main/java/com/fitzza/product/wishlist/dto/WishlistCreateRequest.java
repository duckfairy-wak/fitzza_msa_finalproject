package com.fitzza.product.wishlist.dto;

import io.swagger.v3.oas.annotations.media.Schema;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;

@Schema(description = "찜 추가 요청")
public record WishlistCreateRequest(
        @Schema(description = "상품 ID", example = "1")
        @NotBlank @Size(max = 100) String itemId) {
}
