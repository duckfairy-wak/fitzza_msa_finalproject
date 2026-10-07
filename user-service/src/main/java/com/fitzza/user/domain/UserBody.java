package com.fitzza.user.domain;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.EnumType;
import jakarta.persistence.Enumerated;
import jakarta.persistence.Id;
import jakarta.persistence.PrePersist;
import jakarta.persistence.PreUpdate;
import jakarta.persistence.Table;
import java.time.Instant;

@Entity
@Table(name = "user_body")
public class UserBody {

    @Id
    @Column(name = "user_id")
    private Long userId;

    @Column(name = "height")
    private Float height;

    @Column(name = "weight")
    private Float weight;

    @Enumerated(EnumType.STRING)
    @Column(name = "gender", length = 1)
    private Gender gender;

    @Column(name = "preferred_styles")
    private String preferredStyles;

    @Column(name = "body_type", length = 50)
    private String bodyType;

    @Column(name = "preferred_fit", length = 50)
    private String preferredFit;

    @Column(name = "shoe_size")
    private Integer shoeSize;

    @Column(name = "updated_at", nullable = false)
    private Instant updatedAt;

    protected UserBody() {
    }

    private UserBody(Long userId) {
        this.userId = userId;
    }

    // 온보딩을 건너뛴 사용자도 프로필 조회·수정이 같은 행을 대상으로 하도록 가입 시 빈 행을 만든다.
    public static UserBody emptyFor(Long userId) {
        return new UserBody(userId);
    }

    @PrePersist
    @PreUpdate
    void markUpdated() {
        this.updatedAt = Instant.now();
    }

    public Long getUserId() {
        return userId;
    }
}
