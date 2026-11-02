package com.fitzza.community.client;

import java.time.Duration;
import java.util.List;
import java.util.Optional;

// 공유하려는 가상 피팅 결과를 피팅 서비스에서 확인하는 자리. 테스트에서는 가짜 구현으로 바꿔 끼운다.
public interface FittingResults {

    String COMPLETED = "COMPLETED";

    // 없는 피팅이면 빈 값이다. 피팅 서비스가 응답하지 않거나 주소가 설정되지 않았으면 RestClientException을 던진다.
    Optional<FittingResult> findFitting(long fittingId, Long userId);

    // 응답을 timeout까지만 기다린다. 넘기면 RestClientException을 던진다. 기본 구현은 시간 제한 없이 위 메서드를 부른다.
    default Optional<FittingResult> findFitting(long fittingId, Long userId, Duration timeout) {
        return findFitting(fittingId, userId);
    }

    // owned: 요청한 사용자의 피팅인지. status가 COMPLETED일 때만 resultImageUrl이 있다.
    record FittingResult(boolean owned, String status, String resultImageUrl, List<ResultProduct> products) {
    }
}
