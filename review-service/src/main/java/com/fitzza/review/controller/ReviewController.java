package com.fitzza.review.controller;

import com.fitzza.review.config.OpenApiConfig;
import com.fitzza.review.domain.ReviewSort;
import com.fitzza.review.dto.ErrorResponse;
import com.fitzza.review.dto.ReviewCreateRequest;
import com.fitzza.review.dto.ReviewCreatedResponse;
import com.fitzza.review.dto.ReviewPageResponse;
import com.fitzza.review.dto.ReviewUpdateRequest;
import com.fitzza.review.dto.ReviewUpdatedResponse;
import com.fitzza.review.security.AuthHeaders;
import com.fitzza.review.service.ReviewService;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.Parameter;
import io.swagger.v3.oas.annotations.media.Content;
import io.swagger.v3.oas.annotations.media.Schema;
import io.swagger.v3.oas.annotations.responses.ApiResponse;
import io.swagger.v3.oas.annotations.responses.ApiResponses;
import io.swagger.v3.oas.annotations.security.SecurityRequirement;
import io.swagger.v3.oas.annotations.tags.Tag;
import jakarta.validation.Valid;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PatchMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.ResponseStatus;
import org.springframework.web.bind.annotation.RestController;

@Tag(name = "리뷰", description = "상품 리뷰. 목록은 로그인 없이 보고, 작성·수정·삭제는 로그인이 필요하다.")
@RestController
@RequestMapping("/api/reviews")
public class ReviewController {

    private final ReviewService reviewService;

    public ReviewController(ReviewService reviewService) {
        this.reviewService = reviewService;
    }

    @Operation(
            summary = "상품 리뷰 목록",
            description = "page는 0~10000, size는 1~100(기본 20). sort는 LATEST(기본)·RATING_DESC·RATING_ASC.")
    @ApiResponses({
        @ApiResponse(responseCode = "200", description = "조회 성공"),
        @ApiResponse(
                responseCode = "400",
                description = "INVALID_REQUEST: productId가 없거나 1 미만, 또는 page(0~10000)·size(1~100)·sort가 잘못됨",
                content = @Content(schema = @Schema(implementation = ErrorResponse.class)))
    })
    @GetMapping
    public ReviewPageResponse findByProduct(
            @Parameter(description = "상품 ID(1 이상)") @RequestParam("productId") Long productId,
            @RequestParam(name = "page", defaultValue = "0") int page,
            @RequestParam(name = "size", defaultValue = "20") int size,
            @RequestParam(name = "sort", defaultValue = "LATEST") ReviewSort sort) {
        return reviewService.findByProduct(productId, page, size, sort);
    }

    @Operation(
            summary = "리뷰 작성",
            description = "내가 주문한(취소하지 않은) 주문 상품에만 쓸 수 있다. 주문 상품 하나에 리뷰 하나. 별점은 1~5 정수.",
            security = @SecurityRequirement(name = OpenApiConfig.BEARER_AUTH))
    @ApiResponses({
        @ApiResponse(responseCode = "201", description = "작성 성공"),
        @ApiResponse(
                responseCode = "400",
                description = "INVALID_REQUEST: 빈 값·별점 범위 / ORDER_ITEM_PRODUCT_MISMATCH: 주문한 상품과 다름",
                content = @Content(schema = @Schema(implementation = ErrorResponse.class))),
        @ApiResponse(
                responseCode = "401",
                description = "UNAUTHENTICATED: 로그인 필요",
                content = @Content(schema = @Schema(implementation = ErrorResponse.class))),
        @ApiResponse(
                responseCode = "403",
                description = "NOT_ORDER_OWNER: 남의 주문",
                content = @Content(schema = @Schema(implementation = ErrorResponse.class))),
        @ApiResponse(
                responseCode = "404",
                description = "ORDER_ITEM_NOT_FOUND: 없는 주문 상품",
                content = @Content(schema = @Schema(implementation = ErrorResponse.class))),
        @ApiResponse(
                responseCode = "409",
                description = "DUPLICATE_REVIEW: 이미 작성 / ORDER_CANCELED: 취소된 주문",
                content = @Content(schema = @Schema(implementation = ErrorResponse.class))),
        @ApiResponse(
                responseCode = "503",
                description = "ORDER_LOOKUP_UNAVAILABLE: 주문 서비스에서 주문을 확인하지 못함",
                content = @Content(schema = @Schema(implementation = ErrorResponse.class)))
    })
    @PostMapping
    @ResponseStatus(HttpStatus.CREATED)
    public ReviewCreatedResponse create(
            @Parameter(hidden = true) @RequestHeader(AuthHeaders.USER_ID) Long userId,
            @Valid @RequestBody ReviewCreateRequest request) {
        return reviewService.create(userId, request);
    }

    @Operation(
            summary = "리뷰 수정",
            description = "작성자만 수정한다. 별점·내용·사진을 통째로 바꾸며, imageUrl을 빼면 사진이 지워진다.",
            security = @SecurityRequirement(name = OpenApiConfig.BEARER_AUTH))
    @ApiResponses({
        @ApiResponse(responseCode = "200", description = "수정 성공"),
        @ApiResponse(
                responseCode = "400",
                description = "INVALID_REQUEST: 빈 값·별점 범위",
                content = @Content(schema = @Schema(implementation = ErrorResponse.class))),
        @ApiResponse(
                responseCode = "401",
                description = "UNAUTHENTICATED: 로그인 필요",
                content = @Content(schema = @Schema(implementation = ErrorResponse.class))),
        @ApiResponse(
                responseCode = "403",
                description = "NOT_AUTHOR: 작성자가 아님",
                content = @Content(schema = @Schema(implementation = ErrorResponse.class))),
        @ApiResponse(
                responseCode = "404",
                description = "REVIEW_NOT_FOUND: 없는 리뷰",
                content = @Content(schema = @Schema(implementation = ErrorResponse.class))),
        @ApiResponse(
                responseCode = "409",
                description = "CONCURRENT_UPDATE: 다른 요청과 겹침",
                content = @Content(schema = @Schema(implementation = ErrorResponse.class)))
    })
    @PatchMapping("/{reviewId}")
    public ReviewUpdatedResponse update(
            @Parameter(hidden = true) @RequestHeader(AuthHeaders.USER_ID) Long userId,
            @PathVariable("reviewId") Long reviewId,
            @Valid @RequestBody ReviewUpdateRequest request) {
        return reviewService.update(userId, reviewId, request);
    }

    @Operation(
            summary = "리뷰 삭제",
            description = "작성자만 삭제한다. 삭제한 주문 상품에는 리뷰를 다시 쓸 수 있다.",
            security = @SecurityRequirement(name = OpenApiConfig.BEARER_AUTH))
    @ApiResponses({
        @ApiResponse(responseCode = "204", description = "삭제 성공"),
        @ApiResponse(
                responseCode = "401",
                description = "UNAUTHENTICATED: 로그인 필요",
                content = @Content(schema = @Schema(implementation = ErrorResponse.class))),
        @ApiResponse(
                responseCode = "403",
                description = "NOT_AUTHOR: 작성자가 아님",
                content = @Content(schema = @Schema(implementation = ErrorResponse.class))),
        @ApiResponse(
                responseCode = "404",
                description = "REVIEW_NOT_FOUND: 없는 리뷰",
                content = @Content(schema = @Schema(implementation = ErrorResponse.class)))
    })
    @DeleteMapping("/{reviewId}")
    @ResponseStatus(HttpStatus.NO_CONTENT)
    public void delete(
            @Parameter(hidden = true) @RequestHeader(AuthHeaders.USER_ID) Long userId,
            @PathVariable("reviewId") Long reviewId) {
        reviewService.delete(userId, reviewId);
    }
}
