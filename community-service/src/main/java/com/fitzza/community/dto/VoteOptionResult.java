package com.fitzza.community.dto;

// ratio는 0~1 사이 값이다. 표가 하나도 없으면 0이다.
public record VoteOptionResult(Long voteOptionId, String label, long count, double ratio) {
}
