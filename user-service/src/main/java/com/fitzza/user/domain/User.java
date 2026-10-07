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
import java.time.Instant;
import java.util.Locale;

@Entity
@Table(name = "users")
public class User {

    public static final String EMAIL_REGEX = "^[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(\\.[A-Za-z0-9-]+)*\\.[A-Za-z]{2,}$";
    public static final String NICKNAME_REGEX = "^[가-힣A-Za-z0-9]{2,10}$";

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    @Column(name = "user_id")
    private Long id;

    @Column(name = "email", nullable = false, unique = true, length = 255)
    private String email;

    @Column(name = "password", nullable = false, length = 255)
    private String password;

    @Column(name = "nickname", nullable = false, unique = true, length = 50)
    private String nickname;

    @Enumerated(EnumType.STRING)
    @Column(name = "status", nullable = false, length = 20)
    private UserStatus status;

    @Column(name = "created_at", nullable = false, updatable = false)
    private Instant createdAt;

    @Column(name = "updated_at", nullable = false)
    private Instant updatedAt;

    protected User() {
    }

    private User(String email, String encodedPassword, String nickname) {
        this.email = email;
        this.password = encodedPassword;
        this.nickname = nickname;
        this.status = UserStatus.ACTIVE;
    }

    public static User create(String email, String encodedPassword, String nickname) {
        return new User(normalizeEmail(email), encodedPassword, nickname);
    }

    // 같은 주소가 대소문자·공백 차이로 중복 가입되지 않도록 저장과 조회에 같은 규칙을 쓴다.
    public static String normalizeEmail(String email) {
        return email.trim().toLowerCase(Locale.ROOT);
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

    public boolean isActive() {
        return status == UserStatus.ACTIVE;
    }

    public Long getId() {
        return id;
    }

    public String getEmail() {
        return email;
    }

    public String getPassword() {
        return password;
    }

    public String getNickname() {
        return nickname;
    }
}
