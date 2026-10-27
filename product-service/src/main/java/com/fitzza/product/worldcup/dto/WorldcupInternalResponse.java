package com.fitzza.product.worldcup.dto;

import com.fitzza.product.product.dto.ProductSummaryResponse;
import com.fitzza.product.worldcup.entity.WorldcupHistoryEntity;
import io.swagger.v3.oas.annotations.media.Schema;
import java.time.Instant;
import java.util.function.UnaryOperator;

@Schema(description = "월드컵 결과 조회(내부 통신용)")
public record WorldcupInternalResponse(
        @Schema(description = "월드컵 이력 ID", example = "1") Long worldcupHistoryId,
        @Schema(description = "요청한 사용자의 월드컵 결과인지 여부") boolean owned,
        @Schema(description = "우승 상품. 소유하지 않은 결과이면 null") ProductSummaryResponse winnerProduct,
        @Schema(description = "완료 일시. 소유하지 않은 결과이면 null") Instant completedAt) {

    public static WorldcupInternalResponse owned(
            WorldcupHistoryEntity history, UnaryOperator<String> resolveImageUrl) {
        return new WorldcupInternalResponse(
                history.getWorldcupHistoryId(),
                true,
                ProductSummaryResponse.from(history.getWinnerProduct(), resolveImageUrl),
                history.getCompletedAt());
    }

    public static WorldcupInternalResponse notOwned(Long worldcupHistoryId) {
        return new WorldcupInternalResponse(worldcupHistoryId, false, null, null);
    }
}
