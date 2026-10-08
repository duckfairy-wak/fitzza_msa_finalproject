package com.fitzza.product.product.service;

import com.fitzza.product.global.dto.PageResponse;
import com.fitzza.product.global.exception.BusinessException;
import com.fitzza.product.global.exception.ErrorCode;
import com.fitzza.product.product.dto.OptionSummaryResponse;
import com.fitzza.product.product.dto.ProductCreateRequest;
import com.fitzza.product.product.dto.ProductDetailResponse;
import com.fitzza.product.product.dto.ProductListResponse;
import com.fitzza.product.product.dto.ProductMeasurementResponse;
import com.fitzza.product.product.dto.ProductOptionCreateRequest;
import com.fitzza.product.product.dto.ProductOptionInternalResponse;
import com.fitzza.product.product.dto.ProductOptionResponse;
import com.fitzza.product.product.dto.ProductSortType;
import com.fitzza.product.product.dto.ProductSummaryResponse;
import com.fitzza.product.product.entity.BrandEntity;
import com.fitzza.product.product.entity.OptionMeasurementEntity;
import com.fitzza.product.product.entity.ProductEntity;
import com.fitzza.product.product.entity.ProductImageEntity;
import com.fitzza.product.product.entity.ProductOptionEntity;
import com.fitzza.product.product.entity.ProductSizeGuideEntity;
import com.fitzza.product.product.entity.ProductStatus;
import com.fitzza.product.product.mapper.ProductDetailMapper;
import com.fitzza.product.product.repository.BrandRepository;
import com.fitzza.product.product.repository.OptionMeasurementRepository;
import com.fitzza.product.product.repository.ProductImageRepository;
import com.fitzza.product.product.repository.ProductOptionRepository;
import com.fitzza.product.product.repository.ProductRepository;
import com.fitzza.product.product.repository.ProductSizeGuideRepository;
import com.fitzza.product.product.repository.ProductSpecifications;
import java.util.ArrayList;
import java.util.Collection;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Set;
import java.util.function.Function;
import java.util.stream.Collectors;
import java.util.stream.IntStream;
import java.util.stream.Stream;
import lombok.RequiredArgsConstructor;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.PageRequest;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
@RequiredArgsConstructor
@Transactional(readOnly = true)
public class ProductService {

    private final ProductRepository productRepository;
    private final BrandRepository brandRepository;
    private final CategoryService categoryService;
    private final ProductOptionRepository productOptionRepository;
    private final OptionMeasurementRepository optionMeasurementRepository;
    private final ProductImageRepository productImageRepository;
    private final ProductSizeGuideRepository productSizeGuideRepository;

    public PageResponse<ProductListResponse> findProducts(
            String categoryL1,
            String categoryL2,
            String subcategory,
            ProductSortType sortType,
            int page,
            int size) {
        PageRequest pageRequest = PageRequest.of(page, size, sortType.toSort());
        Page<ProductEntity> products = productRepository.findAll(
                ProductSpecifications.visibleInCategory(categoryL1, categoryL2, subcategory), pageRequest);
        return PageResponse.from(products.map(ProductListResponse::from));
    }

    public ProductDetailResponse findProduct(Long productId) {
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
                categoryService.findNamesByCode(categoryCodesOf(product)));
    }

    /**
     * 상품을 등록한다. 카테고리는 기준 데이터에 있는 코드인지만 확인하고, 받은 코드 문자열을 그대로 저장한다.
     */
    @Transactional
    public ProductDetailResponse createProduct(ProductCreateRequest request) {
        categoryService.verifyCategoryPath(request.categoryL1(), request.categoryL2(), request.subcategory());
        BrandEntity brand = brandRepository.findById(request.brandId())
                .orElseThrow(() -> new BusinessException(ErrorCode.BRAND_NOT_FOUND));
        List<String> imageUrls = request.imageUrls() == null ? List.of() : request.imageUrls();

        ProductEntity product = productRepository.save(ProductEntity.builder()
                .brand(brand)
                .productName(request.productName())
                .productNameEn(request.productNameEn())
                .styleNo(request.styleNo())
                .gender(request.gender())
                .category1(request.categoryL1())
                .category2(request.categoryL2())
                .subcategory(request.subcategory())
                .price(request.price())
                .normalPrice(request.normalPrice())
                .discountRate(request.discountRate())
                .material(request.material())
                .season(request.season())
                .fitType(request.fitType())
                .features(request.features())
                .description(request.description())
                .imageUrl(imageUrls.stream().findFirst().orElse(null))
                .status(ProductStatus.ON_SALE)
                .build());
        productImageRepository.saveAll(toImages(product, imageUrls));
        productOptionRepository.saveAll(toOptions(product, request.options()));
        return findProduct(product.getProductId());
    }

    private List<ProductImageEntity> toImages(ProductEntity product, List<String> imageUrls) {
        return IntStream.range(0, imageUrls.size())
                .mapToObj(index -> ProductImageEntity.builder()
                        .product(product)
                        .imageUrl(imageUrls.get(index))
                        .sequence(index)
                        .build())
                .toList();
    }

    private List<ProductOptionEntity> toOptions(ProductEntity product, List<ProductOptionCreateRequest> requests) {
        List<ProductOptionEntity> options = new ArrayList<>();
        for (ProductOptionCreateRequest request : requests) {
            options.add(ProductOptionEntity.builder()
                    .product(product)
                    .color(request.color())
                    .size(request.size())
                    .additionalPrice(request.additionalPrice())
                    .build());
        }
        return options;
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
                .map(ProductSummaryResponse::from)
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

    public List<OptionSummaryResponse> findOptionSummaries(List<Long> optionIds) {
        List<Long> distinctIds = optionIds.stream().distinct().toList();
        return productOptionRepository.findAllWithProductByOptionIdIn(distinctIds).stream()
                .map(OptionSummaryResponse::from)
                .toList();
    }

    /** 존재하지 않는 옵션 ID는 오류 없이 결과에서 제외한다. */
    public List<ProductOptionInternalResponse> findProductOptions(List<Long> optionIds) {
        List<Long> distinctIds = optionIds.stream().distinct().toList();
        return productOptionRepository.findAllByOptionIdInOrderByOptionId(distinctIds).stream()
                .map(ProductOptionInternalResponse::from)
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
