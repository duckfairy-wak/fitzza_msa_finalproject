package com.fitzza.product.product.service;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

import com.fitzza.product.product.config.ProductImageProperties;
import java.time.Duration;
import java.util.List;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.ObjectProvider;
import software.amazon.awssdk.services.s3.presigner.S3Presigner;

class ProductImageUrlServiceTest {

    private ProductImageProperties properties;
    private ObjectProvider<S3Presigner> s3Presigner;
    private ProductImageUrlService service;

    @BeforeEach
    @SuppressWarnings("unchecked")
    void setUp() {
        properties = new ProductImageProperties();
        s3Presigner = mock(ObjectProvider.class);
        when(s3Presigner.getIfAvailable()).thenReturn(null);
        service = new ProductImageUrlService(properties, s3Presigner);
    }

    @Test
    void leavesAbsoluteHttpUrlsUnchangedEvenWhenPresignEnabled() {
        properties.setPresignEnabled(true);
        properties.setBucket("fitzza-prod-foundation-databucket-wwng6wfc0hqy");
        String https = "https://image.msscdn.net/images/goods_img/example.jpg";

        assertThat(service.resolve(https)).isEqualTo(https);
        assertThat(service.resolve("http://cdn.example/a.png")).isEqualTo("http://cdn.example/a.png");
    }

    @Test
    void returnsObjectKeyWhenPresignDisabled() {
        properties.setPresignEnabled(false);
        String key = "pipeline/runs/collection-20261025-01/images/products/123/001.jpg";

        assertThat(service.resolve(key)).isEqualTo(key);
    }

    @Test
    void returnsObjectKeyWhenEnabledButBucketMissing() {
        properties.setPresignEnabled(true);
        properties.setBucket(" ");
        String key = "pipeline/runs/x/images/products/1/a.jpg";

        assertThat(service.resolve(key)).isEqualTo(key);
    }

    @Test
    void resolveAllMapsEachValue() {
        properties.setPresignEnabled(false);
        assertThat(service.resolveAll(List.of("a", "https://b/c")))
                .containsExactly("a", "https://b/c");
        assertThat(service.resolveAll(null)).isEmpty();
    }

    @Test
    void defaultTtlIsOneHour() {
        assertThat(properties.getPresignTtl()).isEqualTo(Duration.ofHours(1));
    }
}
