package com.fitzza.community.dto;

import java.time.Instant;

public record VotePostCreatedResponse(Long postId, Instant voteEndAt) {
}
