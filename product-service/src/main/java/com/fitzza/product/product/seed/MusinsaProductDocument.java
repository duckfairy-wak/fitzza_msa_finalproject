package com.fitzza.product.product.seed;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonProperty;
import java.util.List;
import java.util.Map;

/**
 * 무신사 크롤링 JSON 한 파일(상품 1개)의 구조. 저장에 쓰지 않는 필드(review, dataset 등)는 읽지 않는다.
 */
@JsonIgnoreProperties(ignoreUnknown = true)
public record MusinsaProductDocument(
        String source,
        @JsonProperty("source_url") String sourceUrl,
        @JsonProperty("product_id") Long productId,
        String name,
        @JsonProperty("name_en") String nameEn,
        @JsonProperty("style_no") String styleNo,
        GenderInfo gender,
        BrandInfo brand,
        CategoryInfo category,
        SeasonInfo season,
        PriceInfo price,
        List<String> images,
        Map<String, List<String>> features,
        SizeInfo size,
        List<OptionGroupInfo> options,
        @JsonProperty("option_items") List<OptionItemInfo> optionItems) {

    @JsonIgnoreProperties(ignoreUnknown = true)
    public record GenderInfo(String normalized) {
    }

    @JsonIgnoreProperties(ignoreUnknown = true)
    public record BrandInfo(String id, String name, @JsonProperty("name_en") String nameEn) {
    }

    @JsonIgnoreProperties(ignoreUnknown = true)
    public record CategoryInfo(
            String categoryDepth1Code,
            String categoryDepth1Name,
            String categoryDepth2Code,
            String categoryDepth2Name,
            String categoryDepth3Code,
            String categoryDepth3Name) {
    }

    @JsonIgnoreProperties(ignoreUnknown = true)
    public record SeasonInfo(String primary) {
    }

    @JsonIgnoreProperties(ignoreUnknown = true)
    public record PriceInfo(Integer normal, Integer sale, @JsonProperty("discount_rate") Integer discountRate) {
    }

    @JsonIgnoreProperties(ignoreUnknown = true)
    public record SizeInfo(
            @JsonProperty("type_name") String typeName,
            String unit,
            String description,
            @JsonProperty("guide_image") String guideImage,
            List<SizeMeasurementInfo> measurements) {
    }

    @JsonIgnoreProperties(ignoreUnknown = true)
    public record SizeMeasurementInfo(String size, Integer sequence, Map<String, Double> measurements) {
    }

    /** 옵션 그룹(예: 컬러, 사이즈). 옵션 항목의 values는 이 목록과 같은 순서로 값이 들어 있다. */
    @JsonIgnoreProperties(ignoreUnknown = true)
    public record OptionGroupInfo(String name) {
    }

    /** 실제 주문 단위인 옵션 조합(SKU). */
    @JsonIgnoreProperties(ignoreUnknown = true)
    public record OptionItemInfo(
            Long id,
            @JsonProperty("managed_code") String managedCode,
            @JsonProperty("price_delta") Integer priceDelta,
            Boolean activated,
            List<String> values) {
    }
}
