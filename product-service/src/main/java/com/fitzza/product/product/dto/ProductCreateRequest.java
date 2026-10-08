package com.fitzza.product.product.dto;

import com.fitzza.product.product.entity.FitType;
import com.fitzza.product.product.entity.Gender;
import com.fitzza.product.product.entity.Season;
import io.swagger.v3.oas.annotations.media.Schema;
import jakarta.validation.Valid;
import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotEmpty;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Pattern;
import jakarta.validation.constraints.Positive;
import jakarta.validation.constraints.PositiveOrZero;
import jakarta.validation.constraints.Size;
import java.util.List;
import java.util.Map;

/** 카테고리는 이름이 아니라 코드로 받으며, 받은 코드는 변환 없이 그대로 상품에 저장한다. */
@Schema(description = "상품 등록 요청. 카테고리는 이름이 아니라 코드(GET /api/categories의 code)로 전달한다.")
public record ProductCreateRequest(
        @Schema(description = "브랜드 ID", example = "1") @NotNull Long brandId,
        @Schema(description = "상품명", example = "오버핏 헤비 후드 티셔츠") @NotBlank @Size(max = 200) String productName,
        @Schema(description = "영문 상품명", example = "Overfit Heavy Hoodie") @Size(max = 200) String productNameEn,
        @Schema(description = "브랜드 품번", example = "HD-001") @Size(max = 100) String styleNo,
        @Schema(description = "성별") Gender gender,
        @Schema(description = "대분류 카테고리 코드", example = "001")
        @NotBlank @Pattern(regexp = CategoryCodes.PATTERN, message = CategoryCodes.MESSAGE) String categoryL1,
        @Schema(description = "중분류 카테고리 코드. 생략 가능", example = "001004")
        @Pattern(regexp = CategoryCodes.PATTERN, message = CategoryCodes.MESSAGE) String categoryL2,
        @Schema(description = "소분류 카테고리 코드. 중분류가 있을 때만 지정", example = "001004001")
        @Pattern(regexp = CategoryCodes.PATTERN, message = CategoryCodes.MESSAGE) String subcategory,
        @Schema(description = "판매가(원)", example = "42000") @NotNull @Positive Integer price,
        @Schema(description = "정상가(원)", example = "49000") @PositiveOrZero Integer normalPrice,
        @Schema(description = "할인율(%)", example = "14") @Min(0) @Max(100) Integer discountRate,
        @Schema(description = "소재", example = "면 100%") @Size(max = 200) String material,
        @Schema(description = "대표 시즌") Season season,
        @Schema(description = "핏") FitType fitType,
        @Schema(description = "상품 특징(항목명-값 목록)", example = "{\"두께감\": [\"두꺼움\"]}")
        Map<String, List<String>> features,
        @Schema(description = "상품 설명") String description,
        @Schema(description = "상품 이미지 URL 목록(노출 순서). 첫 번째가 대표 이미지")
        @Size(max = 30) List<@NotBlank @Size(max = 500) String> imageUrls,
        @Schema(description = "옵션 목록. 하나 이상 필요") @NotEmpty @Size(max = 100) List<@Valid @NotNull ProductOptionCreateRequest> options) {

    /** 카테고리 코드 형식. 한글 이름처럼 코드가 아닌 값은 요청 단계에서 거부한다. */
    private static final class CategoryCodes {

        private static final String PATTERN = "^[0-9]{1,20}$";
        private static final String MESSAGE = "카테고리는 이름이 아니라 숫자 코드로 전달해야 합니다.";
    }
}
