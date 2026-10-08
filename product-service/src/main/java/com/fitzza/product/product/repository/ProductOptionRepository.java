package com.fitzza.product.product.repository;

import com.fitzza.product.product.entity.ProductOptionEntity;
import java.util.Collection;
import java.util.List;
import org.springframework.data.jpa.repository.EntityGraph;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

public interface ProductOptionRepository extends JpaRepository<ProductOptionEntity, Long> {

    @Query("select o from ProductOptionEntity o where o.product.productId in :productIds order by o.optionId")
    List<ProductOptionEntity> findAllByProductIds(@Param("productIds") Collection<Long> productIds);

    /** 상품 정보를 한 번에 읽어 옵션마다 상품을 추가 조회하지 않는다. 존재하지 않는 ID는 결과에서 빠진다. */
    @EntityGraph(attributePaths = "product")
    List<ProductOptionEntity> findAllByOptionIdInOrderByOptionId(Collection<Long> optionIds);

    @Query("""
            select o from ProductOptionEntity o
            join fetch o.product p
            join fetch p.brand
            where o.optionId in :optionIds
            order by o.optionId
            """)
    List<ProductOptionEntity> findAllWithProductByOptionIdIn(@Param("optionIds") Collection<Long> optionIds);
}
