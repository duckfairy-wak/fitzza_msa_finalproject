package com.fitzza.product.product.controller;

import com.fitzza.product.global.constant.PagingConstants;
import com.fitzza.product.product.dto.OptionSummaryResponse;
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

@Tag(name = "Option Internal", description = "서비스 간 통신용 상품 옵션 API")
@RestController
@RequestMapping("/internal/v1/options")
@RequiredArgsConstructor
public class OptionInternalController {

    private final ProductService productService;

    @Operation(summary = "옵션 요약 일괄 조회",
            description = "옵션 ID 목록에 해당하는 옵션·상품 요약(가격, 판매 상태 포함)을 반환한다. 존재하지 않는 ID는 제외한다.")
    @ApiResponse(responseCode = "200", description = "조회 성공")
    @GetMapping
    public List<OptionSummaryResponse> getOptionSummaries(
            @Parameter(description = "옵션 ID 목록(쉼표 구분 또는 반복 파라미터)", example = "10,11")
            @RequestParam
            @NotEmpty @Size(max = PagingConstants.MAX_INTERNAL_IDS) List<@NotNull Long> optionIds) {
        return productService.findOptionSummaries(optionIds);
    }
}
