package com.fitzza.community.service;

import com.fitzza.community.client.FittingResults;
import com.fitzza.community.client.FittingResults.FittingResult;
import com.fitzza.community.domain.Post;
import com.fitzza.community.domain.SharedType;
import java.time.Duration;
import java.util.Collection;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Optional;
import java.util.function.LongSupplier;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Component;

// 피팅 공유 글에 복사해 둔 결과 이미지 주소 대신, 보여줄 때마다 피팅 서비스에서 지금 쓸 수 있는 주소를 받는다.
// 피팅 결과 이미지는 1시간짜리 Presigned URL이라 저장된 주소는 곧 만료된다.
// 피팅 서비스가 응답하지 않으면 글 조회까지 막지 않고 저장된 주소를 그대로 보여준다.
// 한 번 실패하면 같은 요청 안에서는 더 부르지 않아, 피팅 서비스 장애가 피드를 글 수만큼 느리게 만들지 않는다.
// 실패 없이 느리기만 해도 대기가 쌓이지 않도록, 한 요청에서 쓰는 시간이 예산을 넘으면 남은 피팅은 부르지 않는다.
@Component
public class FittingImages {

    private static final Logger log = LoggerFactory.getLogger(FittingImages.class);

    static final Duration TIME_BUDGET = Duration.ofSeconds(2);

    private final FittingResults fittingResults;
    private final LongSupplier nanoTime;
    private final long timeBudgetNanos;

    @Autowired
    public FittingImages(FittingResults fittingResults) {
        this(fittingResults, System::nanoTime, TIME_BUDGET);
    }

    FittingImages(FittingResults fittingResults, LongSupplier nanoTime, Duration timeBudget) {
        this.fittingResults = fittingResults;
        this.nanoTime = nanoTime;
        this.timeBudgetNanos = timeBudget.toNanos();
    }

    // 피팅 ID별 새 결과 이미지 주소. 피팅 공유 글이 아니면 부르지 않는다.
    public Map<Long, String> latest(Collection<Post> posts) {
        Map<Long, Long> authorByFittingId = new LinkedHashMap<>();
        for (Post post : posts) {
            if (post.isShared() && post.getSharedType() == SharedType.FITTING && post.getSharedId() != null) {
                authorByFittingId.putIfAbsent(post.getSharedId(), post.getUserId());
            }
        }
        if (authorByFittingId.isEmpty()) {
            return Map.of();
        }
        Map<Long, String> imageUrls = new HashMap<>();
        long startedAt = nanoTime.getAsLong();
        for (Map.Entry<Long, Long> entry : authorByFittingId.entrySet()) {
            if (nanoTime.getAsLong() - startedAt >= timeBudgetNanos) {
                log.warn("피팅 결과 이미지 주소 조회가 시간 예산을 넘어 남은 피팅은 저장된 주소를 씁니다");
                return imageUrls;
            }
            Optional<FittingResult> fitting;
            try {
                fitting = fittingResults.findFitting(entry.getKey(), entry.getValue());
            } catch (RuntimeException exception) {
                log.warn("피팅 결과 이미지 주소를 새로 받지 못해 저장된 주소를 씁니다: {}", exception.getMessage());
                return imageUrls;
            }
            fitting.filter(result -> FittingResults.COMPLETED.equals(result.status()))
                    .map(FittingResult::resultImageUrl)
                    .filter(url -> !url.isBlank())
                    .ifPresent(url -> imageUrls.put(entry.getKey(), url));
        }
        return imageUrls;
    }
}
