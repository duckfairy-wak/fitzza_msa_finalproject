package com.fitzza.product.wishlist.controller;

import com.fitzza.product.wishlist.dto.WishlistCheckResponse;
import com.fitzza.product.wishlist.service.WishlistService;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.Parameter;
import io.swagger.v3.oas.annotations.responses.ApiResponse;
import io.swagger.v3.oas.annotations.tags.Tag;
import jakarta.validation.constraints.NotBlank;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@Tag(name = "Wishlist Internal", description = "서비스 간 통신용 찜 API")
@RestController
@RequestMapping("/internal/v1/wishlists")
@RequiredArgsConstructor
public class WishlistInternalController {

    private final WishlistService wishlistService;

    @Operation(summary = "찜 소유 확인", description = "사용자가 해당 상품을 찜했는지 확인한다.")
    @ApiResponse(responseCode = "200", description = "확인 성공")
    @GetMapping("/check")
    public WishlistCheckResponse checkWishlist(
            @Parameter(description = "사용자 ID", required = true) @RequestParam Long userId,
            @Parameter(description = "상품 ID", required = true) @RequestParam @NotBlank String itemId) {
        return wishlistService.checkWishlist(userId, itemId);
    }
}
