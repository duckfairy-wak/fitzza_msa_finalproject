package com.fitzza.product.product.dto;

import io.swagger.v3.oas.annotations.media.Schema;
import java.util.List;
import org.springframework.data.domain.Page;

@Schema(description = "상품 목록 페이지")
public record ProductListPageResponse(
        @Schema(description = "현재 페이지 항목") List<ProductListResponse> content,
        @Schema(description = "현재 페이지 번호(0부터 시작)", example = "0") int page,
        @Schema(description = "페이지 크기", example = "20") int size,
        @Schema(description = "전체 항목 수", example = "125") long totalElements,
        @Schema(description = "전체 페이지 수", example = "7") int totalPages,
        @Schema(description = "다음 페이지 존재 여부") boolean hasNext,
        @Schema(description = "적용된 정렬. TIME_DESC, PRICE_ASC 또는 PRICE_DESC", example = "TIME_DESC") String sort) {

    public static ProductListPageResponse from(Page<ProductListResponse> page, ProductSortType sort) {
        return new ProductListPageResponse(
                page.getContent(),
                page.getNumber(),
                page.getSize(),
                page.getTotalElements(),
                page.getTotalPages(),
                page.hasNext(),
                sort.name());
    }
}
