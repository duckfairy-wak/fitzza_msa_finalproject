package com.fitzza.user.domain;

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
import jakarta.persistence.UniqueConstraint;
import java.time.Instant;
import java.util.Locale;

@Entity
@Table(name = "users", uniqueConstraints = {
    @UniqueConstraint(name = User.EMAIL_UNIQUE_CONSTRAINT, columnNames = "email"),
    @UniqueConstraint(name = User.NICKNAME_UNIQUE_CONSTRAINT, columnNames = "nickname")
})
public class User {

    public static final String EMAIL_UNIQUE_CONSTRAINT = "uk_users_email";
    public static final String NICKNAME_UNIQUE_CONSTRAINT = "uk_users_nickname";

    public static final String EMAIL_REGEX = "^[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(\\.[A-Za-z0-9-]+)*\\.[A-Za-z]{2,}$";
    public static final String NICKNAME_REGEX = "^[가-힣A-Za-z0-9]{2,10}$";

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    @Column(name = "user_id")
    private Long id;

    @Column(name = "email", nullable = false, length = 255)
    private String email;

    @Column(name = "password", nullable = false, length = 255)
    private String password;

    @Column(name = "nickname", nullable = false, length = 50)
    private String nickname;

    @Enumerated(EnumType.STRING)
    @Column(name = "status", nullable = false, length = 20)
    private UserStatus status;

    @Column(name = "created_at", nullable = false, updatable = false)
    private Instant createdAt;

    @Column(name = "updated_at", nullable = false)
    private Instant updatedAt;

    /**
     * JPA가 저장된 사용자 정보를 복원할 때 사용하는 생성자이다.
     */
    protected User() {
    }

    /**
     * 정규화된 이메일과 인코딩된 비밀번호로 활성 사용자를 초기화한다.
     */
    private User(String email, String encodedPassword, String nickname) {
        this.email = email;
        this.password = encodedPassword;
        this.nickname = nickname;
        this.status = UserStatus.ACTIVE;
    }

    /**
     * 이메일을 정규화하고 아직 저장되지 않은 활성 사용자를 만든다.
     *
     * @param email 정규화할 이메일
     * @param encodedPassword 호출자가 미리 인코딩한 비밀번호
     * @param nickname 검증된 닉네임
     * @return 저장 전 사용자 엔티티
     */
    public static User create(String email, String encodedPassword, String nickname) {
        return new User(normalizeEmail(email), encodedPassword, nickname);
    }

    /**
     * 저장과 조회에 같은 규칙을 적용하도록 이메일의 양끝 공백을 제거하고 소문자로 변환한다.
     *
     * @param email null이 아닌 이메일
     * @return 로케일에 영향을 받지 않는 정규화된 이메일
     */
    public static String normalizeEmail(String email) {
        return email.trim().toLowerCase(Locale.ROOT);
    }

    /**
     * 최초 저장 직전에 생성 시각과 수정 시각을 같은 값으로 설정한다.
     */
    @PrePersist
    void markCreated() {
        Instant now = Instant.now();
        this.createdAt = now;
        this.updatedAt = now;
    }

    /**
     * JPA 갱신 직전에 수정 시각을 기록한다.
     */
    @PreUpdate
    void markUpdated() {
        this.updatedAt = Instant.now();
    }

    /**
     * 로그인을 허용하는 ACTIVE 상태인지 반환한다.
     */
    public boolean isActive() {
        return status == UserStatus.ACTIVE;
    }

    /**
     * 데이터베이스가 부여한 사용자 ID를 반환하며 저장 전에는 null일 수 있다.
     */
    public Long getId() {
        return id;
    }

    /**
     * 저장 및 중복 조회에 사용하는 정규화된 이메일을 반환한다.
     */
    public String getEmail() {
        return email;
    }

    /**
     * 비밀번호 대조에 사용할 인코딩된 값을 반환한다.
     */
    public String getPassword() {
        return password;
    }

    /**
     * 사용자 응답에 표시할 닉네임을 반환한다.
     */
    public String getNickname() {
        return nickname;
    }
}
