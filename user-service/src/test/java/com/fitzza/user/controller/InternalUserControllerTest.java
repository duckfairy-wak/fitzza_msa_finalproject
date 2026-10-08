package com.fitzza.user.controller;

import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.fitzza.user.dto.NicknameResponse;
import com.fitzza.user.exception.ErrorCode;
import com.fitzza.user.exception.UserApiException;
import com.fitzza.user.service.ProfileService;
import com.fitzza.user.security.InternalUserSecurityConfig;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.NullAndEmptySource;
import org.junit.jupiter.params.provider.ValueSource;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.test.web.servlet.MockMvc;

@WebMvcTest(controllers = InternalUserController.class, properties = {
    "internal.call-token=test-only-internal-call-token",
    "spring.cloud.config.enabled=false"
})
class InternalUserControllerTest {

    private static final String INTERNAL_TOKEN = "test-only-internal-call-token";

    @MockBean
    private ProfileService profileService;

    @Autowired
    private MockMvc mockMvc;

    @ParameterizedTest
    @ValueSource(strings = {"/internal/users", "/internal/users/7/body", "/internal/users/7/body;ignored=value"})
    void missingInternalTokenIsDeniedEvenWithUserIdentityHeaders(String path) throws Exception {
        mockMvc.perform(get(path).param("userIds", "7,8")
                        .header("X-User-Id", "7")
                        .header("Authorization", "Bearer external-user-token"))
                .andExpect(status().isUnauthorized())
                .andExpect(jsonPath("$.code").value("UNAUTHENTICATED"));
        verifyNoInteractions(profileService);
    }

    @ParameterizedTest
    @ValueSource(strings = {"", " ", "wrong-token"})
    void invalidInternalTokensAreDenied(String token) throws Exception {
        for (String path : List.of("/internal/users", "/internal/users/7/body")) {
            mockMvc.perform(get(path).param("userIds", "7,8").header("X-Internal-Token", token))
                    .andExpect(status().isUnauthorized())
                    .andExpect(jsonPath("$.code").value("UNAUTHENTICATED"));
        }
        verifyNoInteractions(profileService);
    }

    @Test
    void authenticationRunsBeforeRequestParameterValidation() throws Exception {
        mockMvc.perform(get("/internal/users"))
                .andExpect(status().isUnauthorized());
        verifyNoInteractions(profileService);
    }

    @ParameterizedTest
    @NullAndEmptySource
    @ValueSource(strings = {" "})
    void missingOrBlankConfiguredTokenIsRejected(String token) {
        assertThatThrownBy(() -> new InternalUserSecurityConfig(token))
                .isInstanceOf(IllegalArgumentException.class);
    }

    @Test
    void nicknamesAreLookedUpFromCommaSeparatedIds() throws Exception {
        when(profileService.findNicknames(List.of(7L, 8L)))
                .thenReturn(List.of(new NicknameResponse(7L, "fitzza"), new NicknameResponse(8L, "newbie")));

        mockMvc.perform(get("/internal/users").param("userIds", "7,8").header("X-Internal-Token", INTERNAL_TOKEN))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$[0].userId").value(7))
                .andExpect(jsonPath("$[0].nickname").value("fitzza"))
                .andExpect(jsonPath("$[1].nickname").value("newbie"));
    }

    @Test
    void nicknameLookupRejectsNonNumericId() throws Exception {
        mockMvc.perform(get("/internal/users").param("userIds", "7,abc").header("X-Internal-Token", INTERNAL_TOKEN))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value("INVALID_INPUT"));
    }

    @Test
    void bodyLookupReturnsOnlyFilledFields() throws Exception {
        when(profileService.getFilledBodyFields(7L)).thenReturn(Map.of("height", 172.5f));

        mockMvc.perform(get("/internal/users/7/body").header("X-Internal-Token", INTERNAL_TOKEN))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.height").value(172.5))
                .andExpect(jsonPath("$.weight").doesNotExist());
    }

    @Test
    void bodyLookupReturnsNotFoundForUnknownUser() throws Exception {
        when(profileService.getFilledBodyFields(999L)).thenThrow(new UserApiException(ErrorCode.USER_NOT_FOUND));

        mockMvc.perform(get("/internal/users/999/body").header("X-Internal-Token", INTERNAL_TOKEN))
                .andExpect(status().isNotFound())
                .andExpect(jsonPath("$.code").value("USER_NOT_FOUND"));
    }
}
