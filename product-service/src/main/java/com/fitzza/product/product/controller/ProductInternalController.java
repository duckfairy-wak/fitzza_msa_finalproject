package com.fitzza.product.product.controller;

import com.fitzza.product.global.constant.PagingConstants;
import com.fitzza.product.product.dto.ProductMeasurementResponse;
import com.fitzza.product.product.dto.ProductSummaryResponse;
import com.fitzza.product.product.service.ProductService;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.Parameter;
import io.swagger.v3.oas.annotations.responses.ApiResponse;
import io.swagger.v3.oas.annotations.tags.Tag;
import jakarta.validation.constraints.NotEmpty;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Size;
import java.util.List;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@Tag(name = "Product Internal", description = "서비스 간 통신용 상품 API")
@RestController
@RequestMapping("/internal/v1/products")
@RequiredArgsConstructor
public class ProductInternalController {

    private final ProductService productService;

    @Operation(summary = "상품 요약 일괄 조회", description = "상품 ID 목록에 해당하는 요약 정보를 요청 순서대로 반환한다. 존재하지 않는 ID는 제외한다.")
    @ApiResponse(responseCode = "200", description = "조회 성공")
    @GetMapping
    public List<ProductSummaryResponse> getProductSummaries(
            @Parameter(description = "상품 ID 목록(쉼표 구분 또는 반복 파라미터)", example = "1,2,3")
            @RequestParam
            @NotEmpty @Size(max = PagingConstants.MAX_INTERNAL_IDS) List<@NotNull Long> productIds) {
        return productService.findProductSummaries(productIds);
    }

    @Operation(summary = "상품 실측 일괄 조회", description = "상품별로 실측이 등록된 옵션의 실측 정보를 반환한다.")
    @ApiResponse(responseCode = "200", description = "조회 성공")
    @GetMapping("/measurements")
    public List<ProductMeasurementResponse> getProductMeasurements(
            @Parameter(description = "상품 ID 목록(쉼표 구분 또는 반복 파라미터)", example = "1,2,3")
            @RequestParam
            @NotEmpty @Size(max = PagingConstants.MAX_INTERNAL_IDS) List<@NotNull Long> productIds) {
        return productService.findProductMeasurements(productIds);
    }
}
