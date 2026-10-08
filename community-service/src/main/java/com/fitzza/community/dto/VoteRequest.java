package com.fitzza.community.dto;

import jakarta.validation.constraints.NotNull;

public record VoteRequest(@NotNull(message = "투표할 선택지를 골라주세요.") Long voteOptionId) {
}
