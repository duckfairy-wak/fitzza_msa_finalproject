package com.fitzza.product.product.service;

import com.fitzza.product.product.config.ProductImageProperties;
import java.time.Duration;
import java.util.List;
import java.util.Optional;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.stereotype.Service;
import org.springframework.util.StringUtils;
import software.amazon.awssdk.services.s3.model.GetObjectRequest;
import software.amazon.awssdk.services.s3.presigner.S3Presigner;
import software.amazon.awssdk.services.s3.presigner.model.GetObjectPresignRequest;

/**
 * DB에 저장된 상품 이미지 값을 API용 URL로 바꾼다.
 *
 * <ul>
 *   <li>이미 {@code http(s)://} 이면 그대로 둔다(기존 무신사 CDN 등).</li>
 *   <li>그 외는 S3 object key로 보고 Presigned GET URL을 발급한다.</li>
 * </ul>
 */
@Slf4j
@Service
public class ProductImageUrlService {

    private final ProductImageProperties properties;
    private final ObjectProvider<S3Presigner> s3Presigner;

    public ProductImageUrlService(ProductImageProperties properties, ObjectProvider<S3Presigner> s3Presigner) {
        this.properties = properties;
        this.s3Presigner = s3Presigner;
    }

    public String resolve(String stored) {
        if (!StringUtils.hasText(stored)) {
            return stored;
        }
        String value = stored.trim();
        if (isAbsoluteHttpUrl(value) || !properties.isPresignEnabled()) {
            return value;
        }
        String bucket = properties.getBucket();
        if (!StringUtils.hasText(bucket)) {
            log.warn("fitzza.product-images.presign-enabled=true 이지만 bucket이 비어 있어 object key를 그대로 반환합니다.");
            return value;
        }
        S3Presigner presigner = s3Presigner.getIfAvailable();
        if (presigner == null) {
            log.warn("S3Presigner 빈이 없어 object key를 그대로 반환합니다. key={}", abbreviate(value));
            return value;
        }
        try {
            Duration ttl = Optional.ofNullable(properties.getPresignTtl()).orElse(Duration.ofHours(1));
            GetObjectRequest getObject = GetObjectRequest.builder()
                    .bucket(bucket.trim())
                    .key(stripLeadingSlash(value))
                    .build();
            GetObjectPresignRequest presignRequest = GetObjectPresignRequest.builder()
                    .signatureDuration(ttl)
                    .getObjectRequest(getObject)
                    .build();
            return presigner.presignGetObject(presignRequest).url().toExternalForm();
        } catch (RuntimeException exception) {
            log.warn("상품 이미지 Presigned URL 발급 실패, object key를 그대로 반환합니다. key={} ({})",
                    abbreviate(value), exception.toString());
            return value;
        }
    }

    public List<String> resolveAll(List<String> storedValues) {
        if (storedValues == null || storedValues.isEmpty()) {
            return List.of();
        }
        return storedValues.stream().map(this::resolve).toList();
    }

    private static boolean isAbsoluteHttpUrl(String value) {
        String lower = value.toLowerCase();
        return lower.startsWith("https://") || lower.startsWith("http://");
    }

    private static String stripLeadingSlash(String key) {
        return key.startsWith("/") ? key.substring(1) : key;
    }

    private static String abbreviate(String value) {
        return value.length() <= 120 ? value : value.substring(0, 117) + "...";
    }
}
