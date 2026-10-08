package com.fitzza.product.product.repository;

import com.fitzza.product.product.entity.ProductImageEntity;
import java.util.List;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

public interface ProductImageRepository extends JpaRepository<ProductImageEntity, Long> {

    @Query("select i from ProductImageEntity i where i.product.productId = :productId order by i.sequence")
    List<ProductImageEntity> findAllByProductIdOrderBySequence(@Param("productId") Long productId);
}
