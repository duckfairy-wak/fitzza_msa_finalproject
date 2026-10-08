package com.fitzza.community.domain;

import jakarta.persistence.Column;
import jakarta.persistence.EmbeddedId;
import jakarta.persistence.Entity;
import jakarta.persistence.Table;
import java.time.Instant;

// 복합 기본 키(post_id, user_id)가 사용자당 좋아요 한 번을 보장한다.
@Entity
@Table(name = "post_likes")
public class PostLike {

    @EmbeddedId
    private PostLikeId id;

    @Column(name = "created_at", nullable = false, updatable = false)
    private Instant createdAt;

    protected PostLike() {
    }

    public PostLikeId getId() {
        return id;
    }

    public Instant getCreatedAt() {
        return createdAt;
    }
}
