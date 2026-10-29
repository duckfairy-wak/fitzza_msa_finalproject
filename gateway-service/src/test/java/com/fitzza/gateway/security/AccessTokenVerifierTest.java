package com.fitzza.gateway.security;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import io.jsonwebtoken.ExpiredJwtException;
import io.jsonwebtoken.JwtException;
import io.jsonwebtoken.Jwts;
import io.jsonwebtoken.security.Keys;
import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.util.Date;
import javax.crypto.SecretKey;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;

class AccessTokenVerifierTest {

    private static final SecretKey KEY = Keys.hmacShaKeyFor(TestTokens.SECRET.getBytes(StandardCharsets.UTF_8));

    private final AccessTokenVerifier verifier = new AccessTokenVerifier(TestTokens.SECRET);

    @Test
    void returnsTheUserIdOfAValidToken() {
        assertThat(verifier.verify(TestTokens.valid("7"))).isEqualTo(7L);
    }

    @Test
    void rejectsExpiredToken() {
        assertThatThrownBy(() -> verifier.verify(TestTokens.expired("7"))).isInstanceOf(ExpiredJwtException.class);
    }

    @Test
    void rejectsTokenSignedWithAnotherSecret() {
        assertThatThrownBy(() -> verifier.verify(TestTokens.signedWithOtherSecret("7")))
                .isInstanceOf(JwtException.class)
                .isNotInstanceOf(ExpiredJwtException.class);
    }

    @Test
    void rejectsTokenWhosePayloadWasChanged() {
        String[] parts = TestTokens.valid("7").split("\\.");
        String forgedPayload = TestTokens.valid("8").split("\\.")[1];

        assertThatThrownBy(() -> verifier.verify(parts[0] + "." + forgedPayload + "." + parts[2]))
                .isInstanceOf(JwtException.class);
    }

    @Test
    void rejectsTextThatIsNotAToken() {
        assertThatThrownBy(() -> verifier.verify("not-a-token")).isInstanceOf(JwtException.class);
    }

    @Test
    void rejectsTokenWhoseSubjectIsNotAUserId() {
        assertThatThrownBy(() -> verifier.verify(TestTokens.valid("admin")))
                .isInstanceOf(IllegalArgumentException.class);
    }

    @ParameterizedTest
    @ValueSource(strings = {"0", "-1", "9223372036854775808"})
    void rejectsTokenWhoseSubjectIsNotAPositiveUserId(String subject) {
        assertThatThrownBy(() -> verifier.verify(TestTokens.valid(subject)))
                .isInstanceOf(IllegalArgumentException.class);
    }

    @Test
    void rejectsTokenWithoutASubject() {
        String token = Jwts.builder()
                .expiration(Date.from(Instant.now().plusSeconds(600)))
                .signWith(KEY, Jwts.SIG.HS256)
                .compact();

        assertThatThrownBy(() -> verifier.verify(token)).isInstanceOf(IllegalArgumentException.class);
    }

    @Test
    void rejectsTokenThatNeverExpires() {
        String token = Jwts.builder().subject("7").signWith(KEY, Jwts.SIG.HS256).compact();

        assertThatThrownBy(() -> verifier.verify(token)).isInstanceOf(IllegalArgumentException.class);
    }

    @Test
    void rejectsUnsignedToken() {
        String token = Jwts.builder().subject("7").expiration(Date.from(Instant.now().plusSeconds(600))).compact();

        assertThatThrownBy(() -> verifier.verify(token)).isInstanceOf(JwtException.class);
    }

    @Test
    void rejectsTokenThatIsNotValidYet() {
        String token = Jwts.builder().subject("7")
                .expiration(Date.from(Instant.now().plusSeconds(900)))
                .notBefore(Date.from(Instant.now().plusSeconds(300)))
                .signWith(KEY, Jwts.SIG.HS256)
                .compact();

        assertThatThrownBy(() -> verifier.verify(token)).isInstanceOf(JwtException.class);
    }

    // 비밀키가 HS512에도 쓸 수 있을 만큼 길어도 HS256으로 서명한 토큰만 받는다.
    @Test
    void rejectsTokenSignedWithAnotherAlgorithmEvenWithTheSameSecret() {
        String longSecret = "test-only-long-secret-for-hs512-validation-".repeat(2);
        AccessTokenVerifier longSecretVerifier = new AccessTokenVerifier(longSecret);
        String token = Jwts.builder().subject("7")
                .expiration(Date.from(Instant.now().plusSeconds(600)))
                .signWith(Keys.hmacShaKeyFor(longSecret.getBytes(StandardCharsets.UTF_8)), Jwts.SIG.HS512)
                .compact();

        assertThatThrownBy(() -> longSecretVerifier.verify(token))
                .isInstanceOfAny(IllegalArgumentException.class, JwtException.class);
    }

    @Test
    void refusesToStartWithAShortSecret() {
        assertThatThrownBy(() -> new AccessTokenVerifier("too-short")).isInstanceOf(IllegalArgumentException.class);
    }

    @Test
    void readsTheAdminRoleFromTheToken() {
        assertThat(verifier.authenticate(TestTokens.validWithRole("7", "ADMIN")))
                .isEqualTo(new AccessTokenVerifier.VerifiedUser(7L, "ADMIN"));
    }

    // 역할이 없는 예전 토큰과 모르는 값은 일반 사용자로 본다. 대소문자가 다른 값도 관리자로 인정하지 않는다.
    @Test
    void treatsMissingOrUnknownRolesAsRegularUsers() {
        assertThat(verifier.authenticate(TestTokens.valid("7")).role()).isEqualTo("USER");
        assertThat(verifier.authenticate(TestTokens.validWithRole("7", "USER")).role()).isEqualTo("USER");
        assertThat(verifier.authenticate(TestTokens.validWithRole("7", "admin")).role()).isEqualTo("USER");
        assertThat(verifier.authenticate(TestTokens.validWithRole("7", "SUPER")).role()).isEqualTo("USER");
    }
}
