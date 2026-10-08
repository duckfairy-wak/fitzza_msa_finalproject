package com.fitzza.community.dto;

import java.time.Instant;
import java.util.List;

// myVoteOptionId는 로그인하지 않았거나 아직 투표하지 않았으면 null이다.
public record VoteResultResponse(
        List<VoteOptionResult> options, long total, Instant voteEndAt, boolean closed, Long myVoteOptionId) {
}
