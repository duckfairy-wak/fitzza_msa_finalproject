package com.fitzza.product.wishlist.controller;

import com.fitzza.product.global.constant.ApiHeaders;
import com.fitzza.product.global.constant.PagingConstants;
import com.fitzza.product.global.dto.PageResponse;
import com.fitzza.product.global.exception.ApiErrorResponse;
import com.fitzza.product.wishlist.dto.WishlistCreateRequest;
import com.fitzza.product.wishlist.dto.WishlistItemResponse;
import com.fitzza.product.wishlist.dto.WishlistResponse;
import com.fitzza.product.wishlist.service.WishlistService;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.Parameter;
import io.swagger.v3.oas.annotations.media.Content;
import io.swagger.v3.oas.annotations.media.Schema;
import io.swagger.v3.oas.annotations.responses.ApiResponse;
import io.swagger.v3.oas.annotations.responses.ApiResponses;
import io.swagger.v3.oas.annotations.tags.Tag;
import jakarta.validation.Valid;
import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotBlank;
import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.ResponseStatus;
import org.springframework.web.bind.annotation.RestController;

@Tag(name = "Wishlist", description = "찜 API")
@RestController
@RequestMapping("/api/wishlists")
@RequiredArgsConstructor
public class WishlistController {

    private static final String USER_ID_DESCRIPTION = "요청 사용자 ID";

    private final WishlistService wishlistService;

    @Operation(summary = "찜 목록 조회", description = "요청 사용자가 찜한 상품을 최근 순으로 조회한다.")
    @ApiResponse(responseCode = "200", description = "조회 성공")
    @GetMapping
    public PageResponse<WishlistItemResponse> getWishlists(
            @Parameter(description = USER_ID_DESCRIPTION, required = true)
            @RequestHeader(ApiHeaders.USER_ID) Long userId,
            @Parameter(description = "페이지 번호(0부터 시작)")
            @RequestParam(defaultValue = PagingConstants.DEFAULT_PAGE) @Min(0) int page,
            @Parameter(description = "페이지 크기")
            @RequestParam(defaultValue = PagingConstants.DEFAULT_SIZE) @Min(1) @Max(PagingConstants.MAX_SIZE) int size) {
        return wishlistService.findWishlists(userId, page, size);
    }

    @Operation(summary = "찜 추가", description = "이미 찜한 상품이면 기존 항목을 반환한다.")
    @ApiResponses({
            @ApiResponse(responseCode = "200", description = "찜 추가 성공 또는 기존 항목 반환"),
            @ApiResponse(responseCode = "404", description = "상품 없음",
                    content = @Content(schema = @Schema(implementation = ApiErrorResponse.class)))
    })
    @PostMapping
    public WishlistResponse addWishlist(
            @Parameter(description = USER_ID_DESCRIPTION, required = true)
            @RequestHeader(ApiHeaders.USER_ID) Long userId,
            @Valid @RequestBody WishlistCreateRequest request) {
        return wishlistService.addWishlist(userId, request);
    }

    @Operation(summary = "찜 해제", description = "없는 항목을 해제해도 204를 반환한다.")
    @ApiResponse(responseCode = "204", description = "찜 해제 성공")
    @DeleteMapping
    @ResponseStatus(HttpStatus.NO_CONTENT)
    public void removeWishlist(
            @Parameter(description = USER_ID_DESCRIPTION, required = true)
            @RequestHeader(ApiHeaders.USER_ID) Long userId,
            @Parameter(description = "상품 ID", required = true) @RequestParam @NotBlank String itemId) {
        wishlistService.removeWishlist(userId, itemId);
    }
}
