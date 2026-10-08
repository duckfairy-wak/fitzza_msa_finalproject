package com.fitzza.product.product.seed;

import com.fitzza.product.product.entity.BrandEntity;
import com.fitzza.product.product.entity.CategoryEntity;
import com.fitzza.product.product.entity.Gender;
import com.fitzza.product.product.entity.OptionMeasurementEntity;
import com.fitzza.product.product.entity.ProductEntity;
import com.fitzza.product.product.entity.ProductImageEntity;
import com.fitzza.product.product.entity.ProductOptionEntity;
import com.fitzza.product.product.entity.ProductSizeGuideEntity;
import com.fitzza.product.product.entity.ProductStatus;
import com.fitzza.product.product.entity.Season;
import com.fitzza.product.product.seed.MusinsaProductDocument.CategoryInfo;
import com.fitzza.product.product.seed.MusinsaProductDocument.OptionGroupInfo;
import com.fitzza.product.product.seed.MusinsaProductDocument.OptionItemInfo;
import com.fitzza.product.product.seed.MusinsaProductDocument.SizeInfo;
import com.fitzza.product.product.seed.MusinsaProductDocument.SizeMeasurementInfo;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Optional;
import java.util.regex.Pattern;
import java.util.stream.Collectors;
import java.util.stream.IntStream;
import org.springframework.stereotype.Component;
import org.springframework.util.StringUtils;

/**
 * 무신사 JSON 문서를 product-service 엔티티로 변환한다.
 *
 * <p>주요 변환 규칙
 * <ul>
 *   <li>name → productName, price.sale → price, price.normal → normalPrice, images[0] → imageUrl(썸네일)</li>
 *   <li>option_items의 활성(activated) 조합만 옵션으로 만들고, 활성 옵션이 없으면 상품을 SOLD_OUT으로 둔다.</li>
 *   <li>옵션 값 중 이름에 사이즈가 들어간 그룹의 값을 size로, 나머지를 color로 둔다.</li>
 *   <li>실측값 0 이하는 "측정값 없음"이므로 저장하지 않는다.</li>
 * </ul>
 */
@Component
public class MusinsaProductMapper {

    public static final String SOURCE = "musinsa";

    private static final Pattern SIZE_GROUP_NAME = Pattern.compile("사이즈|size", Pattern.CASE_INSENSITIVE);
    private static final Pattern COLOR_GROUP_NAME = Pattern.compile("컬러|색상|color", Pattern.CASE_INSENSITIVE);
    private static final String COLOR_JOIN_DELIMITER = " / ";

    /** 저장에 필요한 필수 값이 없으면 {@link IllegalArgumentException}을 던진다. */
    public void validate(MusinsaProductDocument document) {
        require(document.productId() != null, "product_id가 없습니다.");
        require(StringUtils.hasText(document.name()), "name이 없습니다.");
        require(document.brand() != null && StringUtils.hasText(document.brand().name()), "brand.name이 없습니다.");
        require(document.category() != null && StringUtils.hasText(document.category().categoryDepth1Code())
                        && StringUtils.hasText(document.category().categoryDepth1Name()),
                "category.categoryDepth1Code 또는 categoryDepth1Name이 없습니다.");
        require(document.price() != null && document.price().sale() != null && document.price().sale() > 0,
                "price.sale이 없거나 0 이하입니다.");
    }

    public BrandEntity toBrand(MusinsaProductDocument document) {
        return BrandEntity.builder()
                .brandName(document.brand().name())
                .brandNameEn(blankToNull(document.brand().nameEn()))
                .brandCode(blankToNull(document.brand().id()))
                .build();
    }

    /** 문서의 카테고리 경로(대·중·소분류)를 코드 기준 카테고리 기준 데이터로 변환한다. 코드나 이름이 없는 단계부터는 만들지 않는다. */
    public List<CategoryEntity> toCategories(MusinsaProductDocument document) {
        CategoryInfo category = document.category();
        String[][] codeAndNameByDepth = {
                {category.categoryDepth1Code(), category.categoryDepth1Name()},
                {category.categoryDepth2Code(), category.categoryDepth2Name()},
                {category.categoryDepth3Code(), category.categoryDepth3Name()}
        };
        List<CategoryEntity> categories = new ArrayList<>();
        String parentCode = null;
        for (int index = 0; index < codeAndNameByDepth.length; index++) {
            String code = codeAndNameByDepth[index][0];
            String name = codeAndNameByDepth[index][1];
            if (!StringUtils.hasText(code) || !StringUtils.hasText(name)) {
                break;
            }
            categories.add(CategoryEntity.builder()
                    .categoryCode(code)
                    .categoryName(name)
                    .parentCode(parentCode)
                    .depth(index + 1)
                    .build());
            parentCode = code;
        }
        return categories;
    }

    public ProductEntity toProduct(MusinsaProductDocument document, BrandEntity brand) {
        CategoryInfo category = document.category();
        return ProductEntity.builder()
                .brand(brand)
                .source(SOURCE)
                .sourceProductId(document.productId())
                .sourceUrl(document.sourceUrl())
                .productName(document.name())
                .productNameEn(blankToNull(document.nameEn()))
                .styleNo(blankToNull(document.styleNo()))
                .gender(toGender(document))
                .category1(blankToNull(category.categoryDepth1Code()))
                .category2(blankToNull(category.categoryDepth2Code()))
                .subcategory(blankToNull(category.categoryDepth3Code()))
                .price(document.price().sale())
                .normalPrice(document.price().normal())
                .discountRate(document.price().discountRate())
                .season(toSeason(document))
                .features(document.features())
                .imageUrl(imageUrls(document).stream().findFirst().orElse(null))
                .status(hasActiveOption(document) ? ProductStatus.ON_SALE : ProductStatus.SOLD_OUT)
                .build();
    }

    public List<ProductImageEntity> toImages(MusinsaProductDocument document, ProductEntity product) {
        List<String> urls = imageUrls(document);
        return IntStream.range(0, urls.size())
                .mapToObj(index -> ProductImageEntity.builder()
                        .product(product)
                        .imageUrl(urls.get(index))
                        .sequence(index)
                        .build())
                .toList();
    }

    public Optional<ProductSizeGuideEntity> toSizeGuide(MusinsaProductDocument document, ProductEntity product) {
        SizeInfo size = document.size();
        if (size == null) {
            return Optional.empty();
        }
        return Optional.of(ProductSizeGuideEntity.builder()
                .product(product)
                .typeName(blankToNull(size.typeName()))
                .unit(blankToNull(size.unit()))
                .description(blankToNull(size.description()))
                .guideImageUrl(blankToNull(size.guideImage()))
                .build());
    }

    public List<ProductOptionEntity> toOptions(MusinsaProductDocument document, ProductEntity product) {
        return activeOptionItems(document).stream()
                .map(item -> {
                    OptionAttributes attributes = resolveAttributes(document.options(), item);
                    return ProductOptionEntity.builder()
                            .product(product)
                            .sourceOptionId(item.id())
                            .managedCode(blankToNull(item.managedCode()))
                            .color(attributes.color())
                            .size(attributes.size())
                            .additionalPrice(item.priceDelta())
                            .build();
                })
                .toList();
    }

    /**
     * 저장된 옵션에 사이즈별 실측값을 연결한다. 옵션과 실측의 연결 키는 사이즈 라벨이며,
     * 사이즈 값 → 관리 코드 → 나머지 옵션 값 순으로 일치하는 실측 행을 찾는다.
     */
    public List<OptionMeasurementEntity> toOptionMeasurements(
            MusinsaProductDocument document, List<ProductOptionEntity> savedOptions) {
        Map<String, SizeMeasurementInfo> measurementsBySize = indexMeasurementsBySize(document);
        if (measurementsBySize.isEmpty()) {
            return List.of();
        }
        Map<Long, OptionItemInfo> itemsBySourceId = activeOptionItems(document).stream()
                .collect(Collectors.toMap(OptionItemInfo::id, item -> item, (first, second) -> first));
        List<OptionMeasurementEntity> measurements = new ArrayList<>();
        for (ProductOptionEntity option : savedOptions) {
            OptionItemInfo item = itemsBySourceId.get(option.getSourceOptionId());
            SizeMeasurementInfo found = item == null ? null : findMeasurement(measurementsBySize, option, item);
            Map<String, Object> spec = found == null ? Map.of() : toMeasurementSpec(found.measurements());
            if (!spec.isEmpty()) {
                measurements.add(OptionMeasurementEntity.builder()
                        .option(option)
                        .sizeLabel(found.size())
                        .sequence(found.sequence())
                        .measurementSpec(spec)
                        .build());
            }
        }
        return measurements;
    }

    private SizeMeasurementInfo findMeasurement(
            Map<String, SizeMeasurementInfo> measurementsBySize, ProductOptionEntity option, OptionItemInfo item) {
        List<String> candidates = new ArrayList<>();
        candidates.add(option.getSize());
        candidates.add(item.managedCode());
        if (item.values() != null) {
            candidates.addAll(item.values());
        }
        return candidates.stream()
                .filter(Objects::nonNull)
                .map(measurementsBySize::get)
                .filter(Objects::nonNull)
                .findFirst()
                .orElse(null);
    }

    private Map<String, SizeMeasurementInfo> indexMeasurementsBySize(MusinsaProductDocument document) {
        if (document.size() == null || document.size().measurements() == null) {
            return Map.of();
        }
        return document.size().measurements().stream()
                .filter(measurement -> StringUtils.hasText(measurement.size()) && measurement.measurements() != null)
                .collect(Collectors.toMap(
                        SizeMeasurementInfo::size, measurement -> measurement, (first, second) -> first,
                        LinkedHashMap::new));
    }

    private Map<String, Object> toMeasurementSpec(Map<String, Double> measurements) {
        Map<String, Object> spec = new LinkedHashMap<>();
        measurements.forEach((name, value) -> {
            if (value != null && value > 0) {
                spec.put(name, value);
            }
        });
        return spec;
    }

    private OptionAttributes resolveAttributes(List<OptionGroupInfo> groups, OptionItemInfo item) {
        List<String> values = item.values() == null ? List.of() : item.values();
        if (values.isEmpty()) {
            return new OptionAttributes(null, null);
        }
        if (values.size() == 1) {
            String groupName = groupName(groups, 0);
            boolean colorOnly = COLOR_GROUP_NAME.matcher(groupName).find()
                    && !SIZE_GROUP_NAME.matcher(groupName).find();
            return colorOnly
                    ? new OptionAttributes(blankToNull(values.get(0)), null)
                    : new OptionAttributes(null, blankToNull(values.get(0)));
        }
        int sizeIndex = findSizeIndex(groups, values.size());
        String color = IntStream.range(0, values.size())
                .filter(index -> index != sizeIndex)
                .mapToObj(values::get)
                .filter(StringUtils::hasText)
                .collect(Collectors.joining(COLOR_JOIN_DELIMITER));
        return new OptionAttributes(blankToNull(color), blankToNull(values.get(sizeIndex)));
    }

    /** 이름에 사이즈가 들어간 그룹의 위치를 찾고, 없으면 마지막 값을 사이즈로 본다. */
    private int findSizeIndex(List<OptionGroupInfo> groups, int valueCount) {
        return IntStream.range(0, valueCount)
                .filter(index -> SIZE_GROUP_NAME.matcher(groupName(groups, index)).find())
                .findFirst()
                .orElse(valueCount - 1);
    }

    private String groupName(List<OptionGroupInfo> groups, int index) {
        if (groups == null || index >= groups.size() || groups.get(index).name() == null) {
            return "";
        }
        return groups.get(index).name();
    }

    private List<OptionItemInfo> activeOptionItems(MusinsaProductDocument document) {
        if (document.optionItems() == null) {
            return List.of();
        }
        return document.optionItems().stream()
                .filter(item -> item.id() != null && !Boolean.FALSE.equals(item.activated()))
                .toList();
    }

    private boolean hasActiveOption(MusinsaProductDocument document) {
        return !activeOptionItems(document).isEmpty();
    }

    private List<String> imageUrls(MusinsaProductDocument document) {
        if (document.images() == null) {
            return List.of();
        }
        return document.images().stream().filter(StringUtils::hasText).toList();
    }

    private Gender toGender(MusinsaProductDocument document) {
        if (document.gender() == null || document.gender().normalized() == null) {
            return null;
        }
        return Arrays.stream(Gender.values())
                .filter(gender -> gender.name().equalsIgnoreCase(document.gender().normalized().trim()))
                .findFirst()
                .orElse(null);
    }

    private Season toSeason(MusinsaProductDocument document) {
        if (document.season() == null || document.season().primary() == null) {
            return null;
        }
        return switch (document.season().primary().trim()) {
            case "봄" -> Season.SPRING;
            case "여름" -> Season.SUMMER;
            case "가을" -> Season.FALL;
            case "겨울" -> Season.WINTER;
            default -> null;
        };
    }

    private String blankToNull(String value) {
        return StringUtils.hasText(value) ? value.trim() : null;
    }

    private void require(boolean condition, String message) {
        if (!condition) {
            throw new IllegalArgumentException(message);
        }
    }

    private record OptionAttributes(String color, String size) {
    }
}
