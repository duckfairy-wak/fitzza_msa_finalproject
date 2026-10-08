package com.fitzza.product.product.controller;

import com.fitzza.product.global.constant.PagingConstants;
import com.fitzza.product.global.dto.PageResponse;
import com.fitzza.product.global.exception.ApiErrorResponse;
import com.fitzza.product.product.dto.ProductCreateRequest;
import com.fitzza.product.product.dto.ProductDetailResponse;
import com.fitzza.product.product.dto.ProductListResponse;
import com.fitzza.product.product.dto.ProductSortType;
import com.fitzza.product.product.service.ProductService;
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
import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.ResponseStatus;
import org.springframework.web.bind.annotation.RestController;

@Tag(name = "Product", description = "상품 조회·등록 API")
@RestController
@RequestMapping("/api/products")
@RequiredArgsConstructor
public class ProductController {

    private final ProductService productService;

    @Operation(summary = "상품 목록 조회", description = "카테고리 코드 조건과 정렬 기준으로 노출 가능한 상품(HIDDEN 제외)을 페이지 단위로 조회한다.")
    @ApiResponses({
            @ApiResponse(responseCode = "200", description = "조회 성공"),
            @ApiResponse(responseCode = "400", description = "잘못된 요청 파라미터",
                    content = @Content(schema = @Schema(implementation = ApiErrorResponse.class)))
    })
    @GetMapping
    public PageResponse<ProductListResponse> getProducts(
            @Parameter(description = "대분류 카테고리 코드", example = "001") @RequestParam(required = false) String categoryL1,
            @Parameter(description = "중분류 카테고리 코드", example = "001004") @RequestParam(required = false) String categoryL2,
            @Parameter(description = "소분류 카테고리 코드", example = "001004001") @RequestParam(required = false) String subcategory,
            @Parameter(description = "정렬 기준") @RequestParam(defaultValue = "LATEST") ProductSortType sort,
            @Parameter(description = "페이지 번호(0부터 시작)")
            @RequestParam(defaultValue = PagingConstants.DEFAULT_PAGE) @Min(0) int page,
            @Parameter(description = "페이지 크기")
            @RequestParam(defaultValue = PagingConstants.DEFAULT_SIZE) @Min(1) @Max(PagingConstants.MAX_SIZE) int size) {
        return productService.findProducts(categoryL1, categoryL2, subcategory, sort, page, size);
    }

    @Operation(summary = "상품 상세 조회", description = "상품 기본 정보와 옵션별 실측 정보를 함께 조회한다.")
    @ApiResponses({
            @ApiResponse(responseCode = "200", description = "조회 성공"),
            @ApiResponse(responseCode = "404", description = "상품 없음 또는 비노출 상품",
                    content = @Content(schema = @Schema(implementation = ApiErrorResponse.class)))
    })
    @GetMapping("/{productId}")
    public ProductDetailResponse getProduct(
            @Parameter(description = "상품 ID", example = "1") @PathVariable Long productId) {
        return productService.findProduct(productId);
    }

    @Operation(summary = "상품 등록",
            description = "상품과 옵션을 등록한다. 카테고리는 이름이 아니라 코드로 전달하며 받은 코드를 그대로 저장한다.")
    @ApiResponses({
            @ApiResponse(responseCode = "201", description = "등록 성공"),
            @ApiResponse(responseCode = "400", description = "요청 값 오류 또는 존재하지 않는 카테고리 코드",
                    content = @Content(schema = @Schema(implementation = ApiErrorResponse.class))),
            @ApiResponse(responseCode = "404", description = "브랜드 없음",
                    content = @Content(schema = @Schema(implementation = ApiErrorResponse.class)))
    })
    @PostMapping
    @ResponseStatus(HttpStatus.CREATED)
    public ProductDetailResponse createProduct(@Valid @RequestBody ProductCreateRequest request) {
        return productService.createProduct(request);
    }
}
