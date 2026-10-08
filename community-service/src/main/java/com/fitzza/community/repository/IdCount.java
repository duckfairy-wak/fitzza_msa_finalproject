package com.fitzza.community.repository;

import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;

// 목록 한 페이지의 좋아요·댓글 수를 글마다 따로 세지 않고 한 번에 가져오기 위한 집계 결과.
public record IdCount(Long id, Long total) {

    public static Map<Long, Long> toMap(List<IdCount> counts) {
        return counts.stream().collect(Collectors.toMap(IdCount::id, IdCount::total));
    }
}
