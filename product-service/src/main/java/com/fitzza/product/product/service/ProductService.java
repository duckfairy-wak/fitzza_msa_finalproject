package com.fitzza.product.product.service;

import com.fitzza.product.global.exception.BusinessException;
import com.fitzza.product.global.exception.ErrorCode;
import com.fitzza.product.product.dto.ProductDetailResponse;
import com.fitzza.product.product.dto.ProductListPageResponse;
import com.fitzza.product.product.dto.ProductListResponse;
import com.fitzza.product.product.dto.ProductMeasurementResponse;
import com.fitzza.product.product.dto.ProductOptionInternalResponse;
import com.fitzza.product.product.dto.ProductOptionResponse;
import com.fitzza.product.product.dto.ProductSortType;
import com.fitzza.product.product.dto.ProductSummaryResponse;
import com.fitzza.product.product.entity.OptionMeasurementEntity;
import com.fitzza.product.product.entity.ProductEntity;
import com.fitzza.product.product.entity.ProductOptionEntity;
import com.fitzza.product.product.entity.ProductSizeGuideEntity;
import com.fitzza.product.product.entity.ProductStatus;
import com.fitzza.product.product.mapper.ProductDetailMapper;
import com.fitzza.product.product.repository.OptionMeasurementRepository;
import com.fitzza.product.product.repository.ProductImageRepository;
import com.fitzza.product.product.repository.ProductOptionRepository;
import com.fitzza.product.product.repository.ProductRepository;
import com.fitzza.product.product.repository.ProductSizeGuideRepository;
import com.fitzza.product.product.repository.ProductSpecifications;
import com.fitzza.product.wishlist.service.WishlistService;
import java.util.Collection;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Set;
import java.util.function.Function;
import java.util.stream.Collectors;
import java.util.stream.Stream;
import lombok.RequiredArgsConstructor;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.PageRequest;
import org.springframework.stereotype.Service;
import org.springframework.util.StringUtils;
import org.springframework.transaction.annotation.Transactional;

@Service
@RequiredArgsConstructor
@Transactional(readOnly = true)
public class ProductService {

    private final ProductRepository productRepository;
    private final CategoryService categoryService;
    private final ProductOptionRepository productOptionRepository;
    private final OptionMeasurementRepository optionMeasurementRepository;
    private final ProductImageRepository productImageRepository;
    private final ProductSizeGuideRepository productSizeGuideRepository;
    private final WishlistService wishlistService;
    private final ProductImageUrlService productImageUrlService;

    public ProductListPageResponse findProducts(
            String category, ProductSortType sortType, int page, int size, Long userId) {
        validateCategoryLength(category);
        PageRequest pageRequest = PageRequest.of(page, size, sortType.toSort());
        Page<ProductEntity> products = productRepository.findAll(
                ProductSpecifications.visibleInCategory(category), pageRequest);
        Set<Long> wishlistedIds = userId == null
                ? Set.of()
                : wishlistService.findWishlistedProductIds(
                        userId,
                        products.getContent().stream().map(ProductEntity::getProductId).toList());
        Page<ProductListResponse> mapped = products.map(product -> ProductListResponse.from(
                product,
                userId == null ? null : wishlistedIds.contains(product.getProductId()),
                productImageUrlService::resolve));
        return ProductListPageResponse.from(mapped, sortType);
    }

    private void validateCategoryLength(String category) {
        if (!StringUtils.hasText(category)) {
            return;
        }
        int length = category.trim().length();
        if (length != 3 && length != 6 && length != 9) {
            throw new BusinessException(ErrorCode.INVALID_REQUEST, "카테고리 코드 길이는 3, 6, 9여야 합니다.");
        }
    }

    public ProductDetailResponse findProduct(Long productId, Long userId) {
        ProductEntity product = productRepository.findWithBrandByProductId(productId)
                .filter(found -> found.getStatus() != ProductStatus.HIDDEN)
                .orElseThrow(() -> new BusinessException(ErrorCode.PRODUCT_NOT_FOUND));
        List<ProductOptionEntity> options = productOptionRepository.findAllByProductIds(List.of(productId));
        ProductSizeGuideEntity sizeGuide = productSizeGuideRepository.findById(productId).orElse(null);
        return ProductDetailMapper.toResponse(
                product,
                productImageRepository.findAllByProductIdOrderBySequence(productId),
                sizeGuide,
                options,
                loadMeasurements(options),
                categoryService.findNamesByCode(categoryCodesOf(product)),
                userId == null ? null : wishlistService.isWishlisted(userId, productId),
                productImageUrlService::resolve);
    }

    private Set<String> categoryCodesOf(ProductEntity product) {
        return Stream.of(product.getCategory1(), product.getCategory2(), product.getSubcategory())
                .filter(Objects::nonNull)
                .collect(Collectors.toSet());
    }

    public List<ProductSummaryResponse> findProductSummaries(List<Long> productIds) {
        List<Long> distinctIds = productIds.stream().distinct().toList();
        Map<Long, ProductEntity> productsById = loadProductsById(distinctIds);
        return distinctIds.stream()
                .map(productsById::get)
                .filter(Objects::nonNull)
                .map(product -> ProductSummaryResponse.from(product, productImageUrlService::resolve))
                .toList();
    }

    public List<ProductMeasurementResponse> findProductMeasurements(List<Long> productIds) {
        List<Long> distinctIds = productIds.stream().distinct().toList();
        Map<Long, ProductEntity> productsById = loadProductsById(distinctIds);
        if (productsById.isEmpty()) {
            return List.of();
        }
        List<ProductOptionEntity> options = productOptionRepository.findAllByProductIds(productsById.keySet());
        Map<Long, OptionMeasurementEntity> measurements = loadMeasurements(options);
        Map<Long, List<ProductOptionResponse>> optionsByProductId = options.stream()
                .filter(option -> measurements.containsKey(option.getOptionId()))
                .collect(Collectors.groupingBy(
                        option -> option.getProduct().getProductId(),
                        Collectors.mapping(
                                option -> ProductOptionResponse.of(
                                        option, measurements.get(option.getOptionId()).getMeasurementSpec()),
                                Collectors.toList())));
        return distinctIds.stream()
                .filter(productsById::containsKey)
                .map(productId -> new ProductMeasurementResponse(
                        productId, optionsByProductId.getOrDefault(productId, List.of())))
                .toList();
    }

    /** 존재하지 않는 옵션 ID는 오류 없이 결과에서 제외한다. */
    public List<ProductOptionInternalResponse> findProductOptions(List<Long> optionIds) {
        List<Long> distinctIds = optionIds.stream().distinct().toList();
        return productOptionRepository.findAllWithProductByOptionIdIn(distinctIds).stream()
                .map(option -> ProductOptionInternalResponse.from(option, productImageUrlService::resolve))
                .toList();
    }

    private Map<Long, ProductEntity> loadProductsById(Collection<Long> productIds) {
        return productRepository.findAllWithBrandByProductIdIn(productIds).stream()
                .collect(Collectors.toMap(ProductEntity::getProductId, Function.identity()));
    }

    private Map<Long, OptionMeasurementEntity> loadMeasurements(List<ProductOptionEntity> options) {
        if (options.isEmpty()) {
            return Map.of();
        }
        List<Long> optionIds = options.stream().map(ProductOptionEntity::getOptionId).toList();
        return optionMeasurementRepository.findAllByOptionIdIn(optionIds).stream()
                .collect(Collectors.toMap(OptionMeasurementEntity::getOptionId, Function.identity()));
    }
}
