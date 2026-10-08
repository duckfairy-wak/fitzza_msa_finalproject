package com.fitzza.product.product.mapper;

import com.fitzza.product.product.dto.ProductDetailOptionResponse;
import com.fitzza.product.product.dto.ProductDetailResponse;
import com.fitzza.product.product.dto.SizeGuideResponse;
import com.fitzza.product.product.dto.SizeMeasurementResponse;
import com.fitzza.product.product.entity.BrandEntity;
import com.fitzza.product.product.entity.OptionMeasurementEntity;
import com.fitzza.product.product.entity.ProductEntity;
import com.fitzza.product.product.entity.ProductImageEntity;
import com.fitzza.product.product.entity.ProductOptionEntity;
import com.fitzza.product.product.entity.ProductSizeGuideEntity;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 상품 관련 엔티티를 상세 응답 DTO로 변환한다.
 *
 * <p>대표 이미지(thumbnailUrl)는 상품 엔티티의 imageUrl, 판매가(price)는 상품 엔티티의 price에서 가져온다.
 */
public final class ProductDetailMapper {

    private ProductDetailMapper() {
    }

    public static ProductDetailResponse toResponse(
            ProductEntity product,
            List<ProductImageEntity> images,
            ProductSizeGuideEntity sizeGuide,
            List<ProductOptionEntity> options,
            Map<Long, OptionMeasurementEntity> measurementsByOptionId,
            Map<String, String> categoryNamesByCode) {
        BrandEntity brand = product.getBrand();
        return new ProductDetailResponse(
                product.getProductId(),
                product.getProductName(),
                product.getProductNameEn(),
                product.getStyleNo(),
                brand.getBrandId(),
                brand.getBrandName(),
                brand.getBrandNameEn(),
                product.getCategory1(),
                product.getCategory2(),
                product.getSubcategory(),
                product.getCategoryCode(),
                categoryNamesByCode.get(product.getCategory1()),
                categoryNamesByCode.get(product.getCategory2()),
                categoryNamesByCode.get(product.getSubcategory()),
                product.getPrice(),
                product.getNormalPrice(),
                product.getDiscountRate(),
                product.getGender(),
                product.getSeason(),
                product.getMaterial(),
                product.getFitType(),
                product.getFeatures(),
                product.getDescription(),
                product.getImageUrl(),
                toImageUrls(product, images),
                toSizeGuide(sizeGuide, toSizeMeasurements(options, measurementsByOptionId)),
                options.stream().map(ProductDetailOptionResponse::from).toList(),
                product.getStatus(),
                product.getCreatedAt(),
                product.getUpdatedAt());
    }

    /** 이미지 행이 없는 상품은 대표 이미지만 노출한다. */
    private static List<String> toImageUrls(ProductEntity product, List<ProductImageEntity> images) {
        if (!images.isEmpty()) {
            return images.stream().map(ProductImageEntity::getImageUrl).toList();
        }
        return product.getImageUrl() == null ? List.of() : List.of(product.getImageUrl());
    }

    private static SizeGuideResponse toSizeGuide(
            ProductSizeGuideEntity sizeGuide, List<SizeMeasurementResponse> measurements) {
        if (sizeGuide == null) {
            return measurements.isEmpty() ? null : new SizeGuideResponse(null, null, null, null, measurements);
        }
        return new SizeGuideResponse(
                sizeGuide.getTypeName(),
                sizeGuide.getUnit(),
                sizeGuide.getDescription(),
                sizeGuide.getGuideImageUrl(),
                measurements);
    }

    /** 색상별 옵션이 같은 사이즈 실측을 공유하므로 사이즈 라벨 기준으로 한 번만 노출한다. */
    private static List<SizeMeasurementResponse> toSizeMeasurements(
            List<ProductOptionEntity> options, Map<Long, OptionMeasurementEntity> measurementsByOptionId) {
        Map<String, SizeMeasurementResponse> bySize = new LinkedHashMap<>();
        for (ProductOptionEntity option : options) {
            OptionMeasurementEntity measurement = measurementsByOptionId.get(option.getOptionId());
            if (measurement == null) {
                continue;
            }
            String size = measurement.getSizeLabel() != null ? measurement.getSizeLabel() : option.getSize();
            bySize.putIfAbsent(size,
                    new SizeMeasurementResponse(size, measurement.getSequence(), measurement.getMeasurementSpec()));
        }
        return bySize.values().stream()
                .sorted(Comparator.comparing(
                        SizeMeasurementResponse::sequence, Comparator.nullsLast(Comparator.naturalOrder())))
                .toList();
    }
}
