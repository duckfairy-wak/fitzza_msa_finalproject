package com.fitzza.community.dto;

import com.fitzza.community.domain.PostCategory;
import com.fitzza.community.domain.PostType;
import java.time.Instant;

public record PostSummaryResponse(
        Long postId,
        String title,
        PostCategory category,
        PostType postType,
        String nickname,
        Instant createdAt,
        String thumbnailUrl,
        long likeCount,
        long commentCount) {
}
