package com.fitzza.product.product.config;

import java.time.Duration;
import org.springframework.boot.context.properties.ConfigurationProperties;

/**
 * 비공개 S3에 저장된 상품 이미지를 API 응답용 Presigned URL로 바꿀 때 쓴다.
 *
 * <p>DB에는 object key(또는 기존 HTTPS URL)를 두고, 응답 직전에만 서명 URL을 만든다.
 */
@ConfigurationProperties(prefix = "fitzza.product-images")
public class ProductImageProperties {

    /**
     * false면 DB 값을 그대로 응답한다. 로컬·테스트 기본값.
     */
    private boolean presignEnabled = false;

    /**
     * 상품 이미지가 있는 버킷. 예: fitzza-prod-foundation-databucket-wwng6wfc0hqy
     */
    private String bucket = "";

    /**
     * Presigned GET 유효 시간. 상품 브라우징을 고려해 기본 1시간.
     */
    private Duration presignTtl = Duration.ofHours(1);

    public boolean isPresignEnabled() {
        return presignEnabled;
    }

    public void setPresignEnabled(boolean presignEnabled) {
        this.presignEnabled = presignEnabled;
    }

    public String getBucket() {
        return bucket;
    }

    public void setBucket(String bucket) {
        this.bucket = bucket;
    }

    public Duration getPresignTtl() {
        return presignTtl;
    }

    public void setPresignTtl(Duration presignTtl) {
        this.presignTtl = presignTtl;
    }
}
