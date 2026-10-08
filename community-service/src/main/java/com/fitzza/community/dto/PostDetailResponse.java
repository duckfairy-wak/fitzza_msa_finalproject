package com.fitzza.community.dto;

import com.fitzza.community.domain.PostCategory;
import com.fitzza.community.domain.PostType;
import java.time.Instant;

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
        Instant updatedAt) {
}
