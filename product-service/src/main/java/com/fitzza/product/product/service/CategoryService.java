package com.fitzza.product.product.service;

import com.fitzza.product.global.exception.BusinessException;
import com.fitzza.product.global.exception.ErrorCode;
import com.fitzza.product.product.dto.CategoryResponse;
import com.fitzza.product.product.entity.CategoryEntity;
import com.fitzza.product.product.entity.ProductStatus;
import com.fitzza.product.product.repository.CategoryPathProjection;
import com.fitzza.product.product.repository.CategoryRepository;
import com.fitzza.product.product.repository.ProductRepository;
import java.util.Collection;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Set;
import java.util.function.Function;
import java.util.stream.Collectors;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Slf4j
@Service
@RequiredArgsConstructor
@Transactional(readOnly = true)
public class CategoryService {

    private final ProductRepository productRepository;
    private final CategoryRepository categoryRepository;

    /**
     * 노출 가능한 상품이 하나 이상 있는 카테고리만 코드 기준 트리로 만든다. 코드와 이름은 모두 카테고리 테이블 기준이며,
     * 테이블에 없는 값(변환되지 않은 이름 등)은 코드와 이름이 같은 노드가 되지 않도록 제외한다.
     */
    public List<CategoryResponse> findCategoryTree() {
        List<CategoryPathProjection> paths = productRepository.findDistinctCategoryPaths(ProductStatus.HIDDEN);
        Map<String, String> namesByCode = findNamesByCode(collectCodes(paths));
        CategoryNode root = new CategoryNode();
        long skippedPaths = paths.stream().filter(path -> !addCategoryPath(root, path, namesByCode)).count();
        if (skippedPaths > 0) {
            log.warn("카테고리 테이블에 없는 코드가 저장된 카테고리 경로 {}건을 목록에서 제외했습니다.", skippedPaths);
        }
        return root.toChildResponses(namesByCode);
    }

    /** 카테고리 코드에 해당하는 이름을 조회한다. 기준 데이터에 없는 코드는 결과에서 빠진다. */
    public Map<String, String> findNamesByCode(Collection<String> codes) {
        Set<String> nonNullCodes = codes.stream().filter(Objects::nonNull).collect(Collectors.toSet());
        return categoryRepository.findAllById(nonNullCodes).stream()
                .collect(Collectors.toMap(CategoryEntity::getCategoryCode, CategoryEntity::getCategoryName));
    }

    /**
     * 코드가 카테고리 기준 데이터에 있고 대분류 → 중분류 → 소분류 계층이 맞는지 확인한다.
     * 이름이 넘어오는 실수를 막기 위해 변환하지 않고 그대로 거부한다.
     */
    public void verifyCategoryPath(String categoryL1, String categoryL2, String subcategory) {
        if (categoryL2 == null && subcategory != null) {
            throw invalidCategory("소분류는 중분류와 함께 지정해야 합니다.");
        }
        Map<String, CategoryEntity> categoriesByCode = categoryRepository
                .findAllById(codesOf(categoryL1, categoryL2, subcategory)).stream()
                .collect(Collectors.toMap(CategoryEntity::getCategoryCode, Function.identity()));
        CategoryEntity levelOne = requireCategory(categoriesByCode, categoryL1, 1, null);
        CategoryEntity levelTwo = categoryL2 == null
                ? null : requireCategory(categoriesByCode, categoryL2, 2, levelOne.getCategoryCode());
        if (subcategory != null) {
            requireCategory(categoriesByCode, subcategory, 3, levelTwo.getCategoryCode());
        }
    }

    private CategoryEntity requireCategory(
            Map<String, CategoryEntity> categoriesByCode, String code, int depth, String parentCode) {
        CategoryEntity category = categoriesByCode.get(code);
        boolean matches = category != null
                && category.getDepth() == depth
                && Objects.equals(category.getParentCode(), parentCode);
        if (!matches) {
            throw invalidCategory("카테고리 코드가 올바르지 않습니다: " + code);
        }
        return category;
    }

    private BusinessException invalidCategory(String message) {
        return new BusinessException(ErrorCode.INVALID_CATEGORY_CODE, message);
    }

    private Set<String> codesOf(String... codes) {
        Set<String> result = new LinkedHashSet<>();
        for (String code : codes) {
            if (code != null) {
                result.add(code);
            }
        }
        return result;
    }

    private Set<String> collectCodes(List<CategoryPathProjection> paths) {
        Set<String> codes = new LinkedHashSet<>();
        for (CategoryPathProjection path : paths) {
            codes.addAll(codesOf(path.getCategory1(), path.getCategory2(), path.getSubcategory()));
        }
        return codes;
    }

    /** 경로의 모든 단계가 기준 데이터에 있으면 트리에 추가하고 true, 하나라도 없으면 추가하지 않고 false를 반환한다. */
    private boolean addCategoryPath(CategoryNode root, CategoryPathProjection path, Map<String, String> namesByCode) {
        boolean known = codesOf(path.getCategory1(), path.getCategory2(), path.getSubcategory()).stream()
                .allMatch(namesByCode::containsKey);
        if (!known) {
            return false;
        }
        CategoryNode levelOne = root.findOrAddChild(path.getCategory1());
        if (path.getCategory2() != null) {
            CategoryNode levelTwo = levelOne.findOrAddChild(path.getCategory2());
            if (path.getSubcategory() != null) {
                levelTwo.findOrAddChild(path.getSubcategory());
            }
        }
        return true;
    }

    /** 같은 코드의 카테고리를 하나로 합치기 위한 트리 구성용 노드. */
    private static final class CategoryNode {

        private final Map<String, CategoryNode> children = new LinkedHashMap<>();

        private CategoryNode findOrAddChild(String code) {
            return children.computeIfAbsent(code, key -> new CategoryNode());
        }

        private List<CategoryResponse> toChildResponses(Map<String, String> namesByCode) {
            return children.entrySet().stream()
                    .map(entry -> new CategoryResponse(
                            entry.getKey(),
                            namesByCode.get(entry.getKey()),
                            entry.getValue().toChildResponses(namesByCode)))
                    .toList();
        }
    }
}
