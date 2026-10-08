package com.fitzza.community.domain;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.EnumType;
import jakarta.persistence.Enumerated;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.PrePersist;
import jakarta.persistence.PreUpdate;
import jakarta.persistence.Table;
import jakarta.persistence.Version;
import java.time.Duration;
import java.time.Instant;
import org.hibernate.annotations.ColumnDefault;

@Entity
@Table(name = "posts")
public class Post {

    public static final int TITLE_MAX_LENGTH = 100;
    public static final int CONTENT_MAX_LENGTH = 5000;
    public static final int IMAGE_URL_MAX_LENGTH = 500;
    public static final Duration VOTE_DURATION = Duration.ofHours(6);

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    @Column(name = "post_id")
    private Long id;

    @Column(name = "user_id", nullable = false, updatable = false)
    private Long userId;

    @Enumerated(EnumType.STRING)
    @Column(name = "post_type", nullable = false, length = 20)
    private PostType postType;

    @Enumerated(EnumType.STRING)
    @Column(name = "category", nullable = false, length = 30)
    private PostCategory category;

    @Column(name = "title", nullable = false, length = 255)
    private String title;

    @Column(name = "content", nullable = false, columnDefinition = "text")
    private String content;

    @Column(name = "image_url", length = IMAGE_URL_MAX_LENGTH)
    private String imageUrl;

    @Column(name = "view_count", nullable = false)
    private long viewCount;

    // 투표글에만 값이 있다. 일반 글은 NULL이다.
    @Column(name = "vote_end_at")
    private Instant voteEndAt;

    // 기본값은 이미 행이 있는 테이블에 이 컬럼을 추가할 때 필요하다.
    @ColumnDefault("false")
    @Column(name = "vote_closed", nullable = false)
    private boolean voteClosed;

    @Column(name = "deleted_at")
    private Instant deletedAt;

    // 수정과 삭제가 겹치면 늦게 끝난 요청이 앞선 변경을 덮어쓰지 않고 실패한다.
    // 기본값은 이미 행이 있는 테이블에 이 컬럼을 추가할 때 필요하다.
    @Version
    @ColumnDefault("0")
    @Column(name = "version", nullable = false)
    private long version;

    @Column(name = "created_at", nullable = false, updatable = false)
    private Instant createdAt;

    @Column(name = "updated_at", nullable = false)
    private Instant updatedAt;

    protected Post() {
    }

    private Post(Long userId, String title, String content, PostCategory category, String imageUrl) {
        this.userId = userId;
        this.postType = PostType.NORMAL;
        this.title = title.trim();
        this.content = content.trim();
        this.category = category;
        this.imageUrl = blankToNull(imageUrl);
    }

    public static Post createNormal(
            Long userId, String title, String content, PostCategory category, String imageUrl) {
        return new Post(userId, title, content, category, imageUrl);
    }

    // 마감 시각은 서버가 정한다. 클라이언트가 보낸 값은 받지 않는다.
    public static Post createVote(Long userId, String title, String content, PostCategory category, Instant now) {
        Post post = new Post(userId, title, content, category, null);
        post.postType = PostType.VOTE;
        post.voteEndAt = now.plus(VOTE_DURATION);
        return post;
    }

    @PrePersist
    void markCreated() {
        Instant now = Instant.now();
        this.createdAt = now;
        this.updatedAt = now;
    }

    @PreUpdate
    void markUpdated() {
        this.updatedAt = Instant.now();
    }

    public boolean isWrittenBy(Long userId) {
        return this.userId.equals(userId);
    }

    public void changeTitle(String title) {
        this.title = title.trim();
    }

    public void changeContent(String content) {
        this.content = content.trim();
    }

    public void changeCategory(PostCategory category) {
        this.category = category;
    }

    // null이나 빈 문자열이 오면 첨부 이미지를 뗀다.
    public void changeImageUrl(String imageUrl) {
        this.imageUrl = blankToNull(imageUrl);
    }

    // 댓글과 알림이 글을 계속 가리킬 수 있도록 행은 남기고 삭제 시각만 기록한다.
    public void delete() {
        this.deletedAt = Instant.now();
    }

    public boolean isDeleted() {
        return deletedAt != null;
    }

    public boolean isVote() {
        return postType == PostType.VOTE;
    }

    // 작성자가 일찍 끝냈거나 마감 시각이 지났으면 더 투표할 수 없다.
    public boolean isVoteClosedAt(Instant now) {
        return voteClosed || (voteEndAt != null && !now.isBefore(voteEndAt));
    }

    public void closeVote() {
        this.voteClosed = true;
    }

    public Instant getVoteEndAt() {
        return voteEndAt;
    }

    public Long getId() {
        return id;
    }

    public Long getUserId() {
        return userId;
    }

    public PostType getPostType() {
        return postType;
    }

    public PostCategory getCategory() {
        return category;
    }

    public String getTitle() {
        return title;
    }

    public String getContent() {
        return content;
    }

    public String getImageUrl() {
        return imageUrl;
    }

    public long getViewCount() {
        return viewCount;
    }

    public Instant getCreatedAt() {
        return createdAt;
    }

    public Instant getUpdatedAt() {
        return updatedAt;
    }

    private static String blankToNull(String value) {
        if (value == null || value.isBlank()) {
            return null;
        }
        return value.trim();
    }
}
