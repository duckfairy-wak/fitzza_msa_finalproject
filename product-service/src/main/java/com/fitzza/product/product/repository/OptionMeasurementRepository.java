package com.fitzza.product.product.repository;

import com.fitzza.product.product.entity.OptionMeasurementEntity;
import java.util.Collection;
import java.util.List;
import org.springframework.data.jpa.repository.JpaRepository;

public interface OptionMeasurementRepository extends JpaRepository<OptionMeasurementEntity, Long> {

    List<OptionMeasurementEntity> findAllByOptionIdIn(Collection<Long> optionIds);
}
