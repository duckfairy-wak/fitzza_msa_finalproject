package com.fitzza.community.dto;

import com.fitzza.community.domain.PostCategory;
import com.fitzza.community.domain.PostType;
import java.time.Instant;
import java.util.List;

// 투표 항목은 투표글에만 채워진다. 일반 글은 voteEndAt이 null이고 voteOptions가 비어 있다.
public record PostDetailResponse(
        Long postId,
        String title,
        String content,
        PostCategory category,
        PostType postType,
        AuthorResponse author,
        String imageUrl,
        long likeCount,
        boolean liked,
        long commentCount,
        long viewCount,
        Instant createdAt,
        Instant updatedAt,
        Instant voteEndAt,
        boolean voteClosed,
        List<VoteOptionResponse> voteOptions) {
}
