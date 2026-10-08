package com.fitzza.product.product.entity;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.FetchType;
import jakarta.persistence.Id;
import jakarta.persistence.JoinColumn;
import jakarta.persistence.MapsId;
import jakarta.persistence.OneToOne;
import jakarta.persistence.Table;
import java.util.Map;
import lombok.AccessLevel;
import lombok.Builder;
import lombok.Getter;
import lombok.NoArgsConstructor;
import org.hibernate.annotations.JdbcTypeCode;
import org.hibernate.type.SqlTypes;

@Entity
@Table(name = "option_measurement")
@Getter
@NoArgsConstructor(access = AccessLevel.PROTECTED)
public class OptionMeasurementEntity {

    @Id
    @Column(name = "option_id")
    private Long optionId;

    @MapsId
    @OneToOne(fetch = FetchType.LAZY, optional = false)
    @JoinColumn(name = "option_id")
    private ProductOptionEntity option;

    /** 실측 표의 사이즈 라벨. 같은 사이즈의 색상별 옵션은 같은 라벨을 공유한다. */
    @Column(name = "size_label", length = 100)
    private String sizeLabel;

    /** 실측 표에서의 사이즈 노출 순서. */
    @Column(name = "sequence")
    private Integer sequence;

    @JdbcTypeCode(SqlTypes.JSON)
    @Column(name = "measurement_spec", nullable = false)
    private Map<String, Object> measurementSpec;

    @Builder
    private OptionMeasurementEntity(
            ProductOptionEntity option, String sizeLabel, Integer sequence, Map<String, Object> measurementSpec) {
        this.option = option;
        this.sizeLabel = sizeLabel;
        this.sequence = sequence;
        this.measurementSpec = measurementSpec;
    }
}
