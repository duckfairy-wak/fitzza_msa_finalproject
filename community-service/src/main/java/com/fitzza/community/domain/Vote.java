package com.fitzza.community.domain;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import jakarta.persistence.UniqueConstraint;
import java.time.Instant;

// (post_id, user_id) 유니크 제약이 한 사람당 한 표를 보장한다.
@Entity
@Table(
        name = "votes",
        uniqueConstraints = @UniqueConstraint(name = "uk_votes_post_user", columnNames = {"post_id", "user_id"}))
public class Vote {

    @Id
    @Column(name = "vote_id", length = 36)
    private String id;

    @Column(name = "post_id", nullable = false, updatable = false)
    private Long postId;

    @Column(name = "user_id", nullable = false, updatable = false)
    private Long userId;

    @Column(name = "vote_option_id", nullable = false, updatable = false)
    private Long voteOptionId;

    @Column(name = "created_at", nullable = false, updatable = false)
    private Instant createdAt;

    protected Vote() {
    }

    public String getId() {
        return id;
    }

    public Long getPostId() {
        return postId;
    }

    public Long getUserId() {
        return userId;
    }

    public Long getVoteOptionId() {
        return voteOptionId;
    }

    public Instant getCreatedAt() {
        return createdAt;
    }
}
