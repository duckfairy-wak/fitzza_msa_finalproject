package com.fitzza.user.controller;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.fitzza.user.dto.SignupRequest;
import com.fitzza.user.exception.ErrorCode;
import com.fitzza.user.exception.GlobalExceptionHandler;
import com.fitzza.user.exception.UserApiException;
import com.fitzza.user.service.UserService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

class UserControllerTest {

    private final UserService userService = mock(UserService.class);
    private MockMvc mockMvc;

    @BeforeEach
    void setUp() {
        mockMvc = MockMvcBuilders.standaloneSetup(new UserController(userService))
                .setControllerAdvice(new GlobalExceptionHandler())
                .build();
    }

    @Test
    void signUpReturnsCreatedWithUserId() throws Exception {
        when(userService.signUp(any(SignupRequest.class))).thenReturn(7L);

        mockMvc.perform(post("/api/v1/users/signup")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(signupJson("fit@example.com", "password1", "fitzza")))
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.userId").value(7));
    }

    @Test
    void signUpRejectsMalformedEmailBeforeCallingService() throws Exception {
        mockMvc.perform(post("/api/v1/users/signup")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(signupJson("not-an-email", "password1", "fitzza")))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value("INVALID_INPUT"));
        verifyNoInteractions(userService);
    }

    @Test
    void signUpRejectsEmailWithoutTopLevelDomain() throws Exception {
        mockMvc.perform(post("/api/v1/users/signup")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(signupJson("fit@example", "password1", "fitzza")))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value("INVALID_INPUT"));
        verifyNoInteractions(userService);
    }

    @Test
    void signUpRejectsPasswordWithSpecialCharacter() throws Exception {
        mockMvc.perform(post("/api/v1/users/signup")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(signupJson("fit@example.com", "password1!", "fitzza")))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value("INVALID_INPUT"));
        verifyNoInteractions(userService);
    }

    @Test
    void signUpRejectsPasswordWithoutDigit() throws Exception {
        mockMvc.perform(post("/api/v1/users/signup")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(signupJson("fit@example.com", "passwordonly", "fitzza")))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value("INVALID_INPUT"));
        verifyNoInteractions(userService);
    }

    @Test
    void signUpAcceptsKoreanAndMixedCaseNickname() throws Exception {
        when(userService.signUp(any(SignupRequest.class))).thenReturn(7L);

        mockMvc.perform(post("/api/v1/users/signup")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(signupJson("fit@example.com", "password1", "민준Fit1")))
                .andExpect(status().isCreated());
    }

    @Test
    void signUpRejectsNicknameWithSpecialCharacter() throws Exception {
        mockMvc.perform(post("/api/v1/users/signup")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(signupJson("fit@example.com", "password1", "fit_zza")))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value("INVALID_INPUT"));
        verifyNoInteractions(userService);
    }

    @Test
    void signUpRejectsNicknameWithWhitespace() throws Exception {
        mockMvc.perform(post("/api/v1/users/signup")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(signupJson("fit@example.com", "password1", "fit zza")))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value("INVALID_INPUT"));
        verifyNoInteractions(userService);
    }

    @Test
    void signUpAcceptsLowercaseOnlyPasswordAndNicknameAtLengthLimits() throws Exception {
        when(userService.signUp(any(SignupRequest.class))).thenReturn(7L);

        mockMvc.perform(post("/api/v1/users/signup")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(signupJson("fit@example.com", "abcdefghijklmnopqrstuvw1", "0123456789")))
                .andExpect(status().isCreated());
    }

    @Test
    void signUpRejectsPasswordLongerThan24Characters() throws Exception {
        mockMvc.perform(post("/api/v1/users/signup")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(signupJson("fit@example.com", "abcdefghijklmnopqrstuvwx1", "fitzza")))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value("INVALID_INPUT"));
        verifyNoInteractions(userService);
    }

    @Test
    void signUpRejectsNicknameLongerThan10Characters() throws Exception {
        mockMvc.perform(post("/api/v1/users/signup")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(signupJson("fit@example.com", "password1", "01234567890")))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value("INVALID_INPUT"));
        verifyNoInteractions(userService);
    }

    @Test
    void signUpReturnsConflictForDuplicateEmail() throws Exception {
        when(userService.signUp(any(SignupRequest.class)))
                .thenThrow(new UserApiException(ErrorCode.DUPLICATE_EMAIL));

        mockMvc.perform(post("/api/v1/users/signup")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(signupJson("fit@example.com", "password1", "fitzza")))
                .andExpect(status().isConflict())
                .andExpect(jsonPath("$.code").value("DUPLICATE_EMAIL"));
    }

    @Test
    void checkEmailReturnsAvailability() throws Exception {
        when(userService.isEmailAvailable("fit@example.com")).thenReturn(false);

        mockMvc.perform(get("/api/v1/users/check-email").param("email", "fit@example.com"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.available").value(false));
    }

    @Test
    void checkNicknameReturnsAvailability() throws Exception {
        when(userService.isNicknameAvailable("fitzza")).thenReturn(true);

        mockMvc.perform(get("/api/v1/users/check-nickname").param("nickname", "fitzza"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.available").value(true));
    }

    @Test
    void checkEmailRejectsMissingParameter() throws Exception {
        mockMvc.perform(get("/api/v1/users/check-email"))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value("INVALID_INPUT"));
    }

    private String signupJson(String email, String password, String nickname) {
        return """
                {"email": "%s", "password": "%s", "nickname": "%s"}
                """.formatted(email, password, nickname);
    }
}
