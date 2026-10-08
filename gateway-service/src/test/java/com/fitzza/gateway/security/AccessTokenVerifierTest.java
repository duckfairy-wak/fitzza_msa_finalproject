package com.fitzza.gateway.security;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import io.jsonwebtoken.ExpiredJwtException;
import io.jsonwebtoken.JwtException;
import org.junit.jupiter.api.Test;

class AccessTokenVerifierTest {

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

    @Test
    void refusesToStartWithAShortSecret() {
        assertThatThrownBy(() -> new AccessTokenVerifier("too-short")).isInstanceOf(IllegalArgumentException.class);
    }
}
