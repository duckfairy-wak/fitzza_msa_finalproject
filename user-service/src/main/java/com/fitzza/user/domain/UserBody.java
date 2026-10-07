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
import java.util.List;

@Entity
@Table(name = "user_body")
public class UserBody {

    private static final String STYLE_DELIMITER = ",";

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

    /**
     * JPA가 저장된 신체 프로필을 복원할 때 사용하는 생성자이다.
     */
    protected UserBody() {
    }

    /**
     * 기존 사용자 ID에 연결된 미입력 신체 프로필을 초기화한다.
     */
    private UserBody(Long userId) {
        this.userId = userId;
    }

    /**
     * 온보딩을 건너뛴 사용자도 같은 프로필 행을 조회·수정하도록 가입 시 빈 프로필을 만든다.
     *
     * @param userId 프로필을 소유할 저장된 사용자 ID
     * @return 신체 정보가 아직 입력되지 않은 프로필
     */
    public static UserBody emptyFor(Long userId) {
        return new UserBody(userId);
    }

    /**
     * 프로필의 최초 저장 또는 갱신 직전에 수정 시각을 기록한다.
     */
    @PrePersist
    @PreUpdate
    void markUpdated() {
        this.updatedAt = Instant.now();
    }

    public void apply(UserBodyUpdate update) {
        update.height().ifPresent(value -> this.height = value);
        update.weight().ifPresent(value -> this.weight = value);
        update.gender().ifPresent(value -> this.gender = value);
        update.bodyType().ifPresent(value -> this.bodyType = value);
        update.preferredFit().ifPresent(value -> this.preferredFit = value);
        update.preferredStyles().ifPresent(value -> this.preferredStyles = joinStyles(value));
        update.shoeSize().ifPresent(value -> this.shoeSize = value);
    }

    /**
     * 프로필의 기본 키이자 소유자인 사용자 ID를 반환한다.
     */
    public Long getUserId() {
        return userId;
    }

    public Float getHeight() {
        return height;
    }

    public Float getWeight() {
        return weight;
    }

    public Gender getGender() {
        return gender;
    }

    public String getBodyType() {
        return bodyType;
    }

    public String getPreferredFit() {
        return preferredFit;
    }

    public List<String> getPreferredStyles() {
        if (preferredStyles == null || preferredStyles.isBlank()) {
            return List.of();
        }
        return List.of(preferredStyles.split(STYLE_DELIMITER));
    }

    public Integer getShoeSize() {
        return shoeSize;
    }

    private String joinStyles(List<String> styles) {
        if (styles == null || styles.isEmpty()) {
            return null;
        }
        return String.join(STYLE_DELIMITER, styles);
    }
}
