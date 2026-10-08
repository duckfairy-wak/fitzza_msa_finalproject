package com.fitzza.user.controller;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.patch;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.fitzza.user.domain.Gender;
import com.fitzza.user.domain.UserBodyUpdate;
import com.fitzza.user.dto.MyProfileResponse;
import com.fitzza.user.dto.OptionResponse;
import com.fitzza.user.dto.ProfileOptionsResponse;
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
    void profileOptionsAreAvailableWithoutLogin() throws Exception {
        when(profileService.getOptions())
                .thenReturn(new ProfileOptionsResponse(
                        List.of(new OptionResponse("STANDARD", "보통 체형")),
                        List.of(new OptionResponse("OVERSIZED", "오버사이즈")),
                        List.of(new OptionResponse("CASUAL", "캐주얼"))));

        mockMvc.perform(get("/api/v1/users/profile/options"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.bodyTypes[0].code").value("STANDARD"))
                .andExpect(jsonPath("$.fits[0].code").value("OVERSIZED"))
                .andExpect(jsonPath("$.styles[0].code").value("CASUAL"));
    }

    @Test
    void myProfileUsesUserIdFromGatewayHeader() throws Exception {
        when(profileService.getMyProfile(7L))
                .thenReturn(new MyProfileResponse("fit@example.com", "fitzza", sampleBody()));

        mockMvc.perform(get("/api/v1/users/me").header(USER_ID_HEADER, "7"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.email").value("fit@example.com"))
                .andExpect(jsonPath("$.nickname").value("fitzza"))
                .andExpect(jsonPath("$.body.height").value(172.5))
                .andExpect(jsonPath("$.body.gender").value("W"))
                .andExpect(jsonPath("$.body.preferredStyles[0]").value("CASUAL"));
    }

    @Test
    void myProfileRequiresUserHeader() throws Exception {
        mockMvc.perform(get("/api/v1/users/me"))
                .andExpect(status().isUnauthorized())
                .andExpect(jsonPath("$.code").value("UNAUTHENTICATED"));
        verifyNoInteractions(profileService);
    }

    @Test
    void myProfileReturnsNotFoundForUnknownUser() throws Exception {
        when(profileService.getMyProfile(7L)).thenThrow(new UserApiException(ErrorCode.USER_NOT_FOUND));

        mockMvc.perform(get("/api/v1/users/me").header(USER_ID_HEADER, "7"))
                .andExpect(status().isNotFound())
                .andExpect(jsonPath("$.code").value("USER_NOT_FOUND"));
    }

    @Test
    void updateMyBodyReturnsUpdatedBody() throws Exception {
        when(profileService.updateMyBody(eq(7L), any(UserBodyUpdate.class))).thenReturn(sampleBody());

        mockMvc.perform(patch("/api/v1/users/me/body")
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
        mockMvc.perform(patch("/api/v1/users/me/body")
                        .header(USER_ID_HEADER, "7")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {"height": 999}
                                """))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value("INVALID_INPUT"));
        verifyNoInteractions(profileService);
    }

    @Test
    void updateMyBodyRequiresUserHeader() throws Exception {
        mockMvc.perform(patch("/api/v1/users/me/body")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {"height": 172.5}
                                """))
                .andExpect(status().isUnauthorized())
                .andExpect(jsonPath("$.code").value("UNAUTHENTICATED"));
        verifyNoInteractions(profileService);
    }

    private UserBodyResponse sampleBody() {
        return new UserBodyResponse(172.5f, 64f, Gender.W, "STANDARD", "OVERSIZED", List.of("CASUAL", "MINIMAL"), 245);
    }
}
