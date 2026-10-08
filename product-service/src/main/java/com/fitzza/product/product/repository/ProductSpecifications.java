package com.fitzza.product.product.repository;

import com.fitzza.product.product.entity.ProductEntity;
import com.fitzza.product.product.entity.ProductStatus;
import jakarta.persistence.criteria.Predicate;
import java.util.ArrayList;
import java.util.List;
import org.springframework.data.jpa.domain.Specification;
import org.springframework.util.StringUtils;

public final class ProductSpecifications {

    private ProductSpecifications() {
    }

    public static Specification<ProductEntity> visibleInCategory(
            String categoryL1, String categoryL2, String subcategory) {
        return (root, query, builder) -> {
            List<Predicate> predicates = new ArrayList<>();
            predicates.add(builder.notEqual(root.get("status"), ProductStatus.HIDDEN));
            if (StringUtils.hasText(categoryL1)) {
                predicates.add(builder.equal(root.get("category1"), categoryL1));
            }
            if (StringUtils.hasText(categoryL2)) {
                predicates.add(builder.equal(root.get("category2"), categoryL2));
            }
            if (StringUtils.hasText(subcategory)) {
                predicates.add(builder.equal(root.get("subcategory"), subcategory));
            }
            return builder.and(predicates.toArray(Predicate[]::new));
        };
    }
}
