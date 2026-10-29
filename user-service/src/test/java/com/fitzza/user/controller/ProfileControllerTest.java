package com.fitzza.user.controller;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.delete;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.patch;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.fitzza.user.domain.Gender;
import com.fitzza.user.domain.UserBodyUpdate;
import com.fitzza.user.domain.UserRole;
import com.fitzza.user.dto.MyProfileResponse;
import com.fitzza.user.dto.UserBodyResponse;
import com.fitzza.user.exception.ErrorCode;
import com.fitzza.user.exception.GlobalExceptionHandler;
import com.fitzza.user.exception.UserApiException;
import com.fitzza.user.service.ProfileService;
import com.fitzza.user.service.UserBodyUpdateParser;
import java.util.List;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

class ProfileControllerTest {

    private static final String USER_ID_HEADER = "X-User-Id";

    private final ProfileService profileService = mock(ProfileService.class);
    private MockMvc mockMvc;

    @BeforeEach
    void setUp() {
        mockMvc = MockMvcBuilders.standaloneSetup(new ProfileController(profileService, new UserBodyUpdateParser()))
                .setControllerAdvice(new GlobalExceptionHandler())
                .build();
    }

    @Test
    void myProfileUsesUserIdFromGatewayHeader() throws Exception {
        when(profileService.getMyProfile(7L))
                .thenReturn(new MyProfileResponse(
                        "fit@example.com", "fitzza", UserRole.USER, Gender.F, 172.5f, 64f, 245, "OVERSIZED", List.of("CASUAL", "MINIMAL")));

        mockMvc.perform(get("/api/users/me").header(USER_ID_HEADER, "7"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.email").value("fit@example.com"))
                .andExpect(jsonPath("$.nickname").value("fitzza"))
                .andExpect(jsonPath("$.role").value("USER"))
                .andExpect(jsonPath("$.gender").value("F"))
                .andExpect(jsonPath("$.height").value(172.5))
                .andExpect(jsonPath("$.shoeSize").value(245))
                .andExpect(jsonPath("$.preferredStyles[0]").value("CASUAL"))
                .andExpect(jsonPath("$.body").doesNotExist())
                .andExpect(jsonPath("$.bodyType").doesNotExist());
    }

    @Test
    void myProfileRequiresUserHeader() throws Exception {
        mockMvc.perform(get("/api/users/me"))
                .andExpect(status().isUnauthorized())
                .andExpect(jsonPath("$.code").value("UNAUTHENTICATED"));
        verifyNoInteractions(profileService);
    }

    @Test
    void myProfileReturnsNotFoundForUnknownUser() throws Exception {
        when(profileService.getMyProfile(7L)).thenThrow(new UserApiException(ErrorCode.USER_NOT_FOUND));

        mockMvc.perform(get("/api/users/me").header(USER_ID_HEADER, "7"))
                .andExpect(status().isNotFound())
                .andExpect(jsonPath("$.code").value("USER_NOT_FOUND"));
    }

    @Test
    void updateMyBodyReturnsUpdatedBody() throws Exception {
        when(profileService.updateMyBody(eq(7L), any(UserBodyUpdate.class))).thenReturn(sampleBody());

        mockMvc.perform(patch("/api/users/me")
                        .header(USER_ID_HEADER, "7")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {"height": 172.5, "weight": null}
                                """))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.height").value(172.5))
                .andExpect(jsonPath("$.shoeSize").value(245));
    }

    @Test
    void updateMyBodyRejectsOutOfRangeValueBeforeCallingService() throws Exception {
        mockMvc.perform(patch("/api/users/me")
                        .header(USER_ID_HEADER, "7")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {"height": 999}
                                """))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value("INVALID_REQUEST"));
        verifyNoInteractions(profileService);
    }

    @Test
    void updateMyBodyRequiresUserHeader() throws Exception {
        mockMvc.perform(patch("/api/users/me")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {"height": 172.5}
                                """))
                .andExpect(status().isUnauthorized())
                .andExpect(jsonPath("$.code").value("UNAUTHENTICATED"));
        verifyNoInteractions(profileService);
    }

    private UserBodyResponse sampleBody() {
        return new UserBodyResponse(Gender.F, 172.5f, 64f, 245, "OVERSIZED", List.of("CASUAL", "MINIMAL"));
    }

    @Test
    void unexpectedFailureReturnsInternalServerErrorWithoutLeakingTheCause() throws Exception {
        when(profileService.getMyProfile(7L)).thenThrow(new IllegalStateException("jdbc url and password"));

        mockMvc.perform(get("/api/users/me").header(USER_ID_HEADER, "7"))
                .andExpect(status().isInternalServerError())
                .andExpect(jsonPath("$.code").value("INTERNAL_SERVER_ERROR"))
                .andExpect(jsonPath("$.message").value(ErrorCode.INTERNAL_SERVER_ERROR.getMessage()));
    }

    @Test
    void unsupportedMethodKeepsItsStatusInTheCommonErrorShape() throws Exception {
        mockMvc.perform(delete("/api/users/me").header(USER_ID_HEADER, "7"))
                .andExpect(status().isMethodNotAllowed())
                .andExpect(jsonPath("$.code").value("METHOD_NOT_ALLOWED"));
    }
}
