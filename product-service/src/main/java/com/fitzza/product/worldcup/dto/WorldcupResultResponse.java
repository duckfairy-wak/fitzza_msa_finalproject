package com.fitzza.product.worldcup.dto;

import com.fitzza.product.product.dto.ProductSummaryResponse;
import com.fitzza.product.worldcup.entity.WorldcupHistoryEntity;
import io.swagger.v3.oas.annotations.media.Schema;
import java.time.Instant;
import java.util.function.UnaryOperator;

@Schema(description = "월드컵 결과")
public record WorldcupResultResponse(
        @Schema(description = "월드컵 이력 ID", example = "1") Long worldcupHistoryId,
        @Schema(description = "우승 상품") ProductSummaryResponse winnerProduct,
        @Schema(description = "완료 일시") Instant completedAt) {

    public static WorldcupResultResponse from(WorldcupHistoryEntity history, UnaryOperator<String> resolveImageUrl) {
        return new WorldcupResultResponse(
                history.getWorldcupHistoryId(),
                ProductSummaryResponse.from(history.getWinnerProduct(), resolveImageUrl),
                history.getCompletedAt());
    }
}
