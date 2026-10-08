package com.fitzza.product.product.dto;

import io.swagger.v3.oas.annotations.media.Schema;
import java.util.List;

@Schema(description = "카테고리 노드. 1단계는 categoryL1, 2단계는 categoryL2, 3단계는 subcategory로 조회한다.")
public record CategoryResponse(
        @Schema(description = "카테고리 코드. 코드가 없는 카테고리는 null", example = "120001") String code,
        @Schema(description = "카테고리 이름", example = "상의") String name,
        @Schema(description = "하위 카테고리 목록") List<CategoryResponse> children) {
}
