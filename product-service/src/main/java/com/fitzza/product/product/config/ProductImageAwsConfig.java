package com.fitzza.product.product.config;

import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import software.amazon.awssdk.services.s3.presigner.S3Presigner;

@Configuration
@EnableConfigurationProperties(ProductImageProperties.class)
public class ProductImageAwsConfig {

    @Bean(destroyMethod = "close")
    @ConditionalOnProperty(prefix = "fitzza.product-images", name = "presign-enabled", havingValue = "true")
    S3Presigner s3Presigner() {
        // 리전·자격 증명은 기본 체인(환경 변수, Pod Identity 등)을 쓴다.
        return S3Presigner.create();
    }
}
