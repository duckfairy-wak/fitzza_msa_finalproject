package com.fitzza.product.product.repository;

import com.fitzza.product.product.entity.BrandEntity;
import java.util.Optional;
import org.springframework.data.jpa.repository.JpaRepository;

public interface BrandRepository extends JpaRepository<BrandEntity, Long> {

    Optional<BrandEntity> findByBrandName(String brandName);
}
