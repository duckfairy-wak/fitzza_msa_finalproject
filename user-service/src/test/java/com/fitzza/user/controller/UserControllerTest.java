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

    /**
     * 실제 요청 검증과 예외 처리기를 사용하는 독립 MockMvc를 구성한다.
     */
    @BeforeEach
    void setUp() {
        mockMvc = MockMvcBuilders.standaloneSetup(new UserController(userService))
                .setControllerAdvice(new GlobalExceptionHandler())
                .build();
    }

    /**
     * 가입 성공 응답이 HTTP 201과 생성된 사용자 ID를 포함하는지 검증한다.
     */
    @Test
    void signUpReturnsCreatedWithUserId() throws Exception {
        when(userService.signUp(any(SignupRequest.class))).thenReturn(7L);

        mockMvc.perform(post("/api/v1/users/signup")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(signupJson("fit@example.com", "password1", "fitzza")))
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.userId").value(7));
    }

    /**
     * 이메일 형식 오류를 서비스 호출 전에 HTTP 400으로 거부하는지 검증한다.
     */
    @Test
    void signUpRejectsMalformedEmailBeforeCallingService() throws Exception {
        mockMvc.perform(post("/api/v1/users/signup")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(signupJson("not-an-email", "password1", "fitzza")))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value("INVALID_INPUT"));
        verifyNoInteractions(userService);
    }

    /**
     * 최상위 도메인이 없는 이메일을 가입 입력으로 허용하지 않는지 검증한다.
     */
    @Test
    void signUpRejectsEmailWithoutTopLevelDomain() throws Exception {
        mockMvc.perform(post("/api/v1/users/signup")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(signupJson("fit@example", "password1", "fitzza")))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value("INVALID_INPUT"));
        verifyNoInteractions(userService);
    }

    /**
     * 영문·숫자 전용 비밀번호 규칙이 특수문자를 거부하는지 검증한다.
     */
    @Test
    void signUpRejectsPasswordWithSpecialCharacter() throws Exception {
        mockMvc.perform(post("/api/v1/users/signup")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(signupJson("fit@example.com", "password1!", "fitzza")))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value("INVALID_INPUT"));
        verifyNoInteractions(userService);
    }

    /**
     * 영문만 있는 비밀번호가 숫자 포함 조건을 충족하지 못하는지 검증한다.
     */
    @Test
    void signUpRejectsPasswordWithoutDigit() throws Exception {
        mockMvc.perform(post("/api/v1/users/signup")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(signupJson("fit@example.com", "passwordonly", "fitzza")))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value("INVALID_INPUT"));
        verifyNoInteractions(userService);
    }

    /**
     * 한글·영문 대소문자·숫자를 섞은 닉네임이 허용되는지 검증한다.
     */
    @Test
    void signUpAcceptsKoreanAndMixedCaseNickname() throws Exception {
        when(userService.signUp(any(SignupRequest.class))).thenReturn(7L);

        mockMvc.perform(post("/api/v1/users/signup")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(signupJson("fit@example.com", "password1", "민준Fit1")))
                .andExpect(status().isCreated());
    }

    /**
     * 닉네임의 밑줄을 허용하지 않고 서비스 호출 전에 차단하는지 검증한다.
     */
    @Test
    void signUpRejectsNicknameWithSpecialCharacter() throws Exception {
        mockMvc.perform(post("/api/v1/users/signup")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(signupJson("fit@example.com", "password1", "fit_zza")))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value("INVALID_INPUT"));
        verifyNoInteractions(userService);
    }

    /**
     * 닉네임 내부 공백을 입력 검증에서 거부하는지 검증한다.
     */
    @Test
    void signUpRejectsNicknameWithWhitespace() throws Exception {
        mockMvc.perform(post("/api/v1/users/signup")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(signupJson("fit@example.com", "password1", "fit zza")))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value("INVALID_INPUT"));
        verifyNoInteractions(userService);
    }

    /**
     * 숫자와 소문자로 된 24자 비밀번호 및 10자 닉네임이 상한에서 허용되는지 검증한다.
     */
    @Test
    void signUpAcceptsLowercaseOnlyPasswordAndNicknameAtLengthLimits() throws Exception {
        when(userService.signUp(any(SignupRequest.class))).thenReturn(7L);

        mockMvc.perform(post("/api/v1/users/signup")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(signupJson("fit@example.com", "abcdefghijklmnopqrstuvw1", "0123456789")))
                .andExpect(status().isCreated());
    }

    /**
     * 비밀번호 길이 상한을 넘긴 요청이 서비스에 도달하지 않는지 검증한다.
     */
    @Test
    void signUpRejectsPasswordLongerThan24Characters() throws Exception {
        mockMvc.perform(post("/api/v1/users/signup")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(signupJson("fit@example.com", "abcdefghijklmnopqrstuvwx1", "fitzza")))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value("INVALID_INPUT"));
        verifyNoInteractions(userService);
    }

    /**
     * 닉네임 길이 상한을 넘긴 요청이 서비스에 도달하지 않는지 검증한다.
     */
    @Test
    void signUpRejectsNicknameLongerThan10Characters() throws Exception {
        mockMvc.perform(post("/api/v1/users/signup")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(signupJson("fit@example.com", "password1", "01234567890")))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value("INVALID_INPUT"));
        verifyNoInteractions(userService);
    }

    /**
     * 이메일 중복 오류가 HTTP 409와 구체적인 오류 코드로 변환되는지 검증한다.
     */
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

    /**
     * 이메일 중복 조회 결과가 available 필드로 전달되는지 검증한다.
     */
    @Test
    void checkEmailReturnsAvailability() throws Exception {
        when(userService.isEmailAvailable("fit@example.com")).thenReturn(false);

        mockMvc.perform(get("/api/v1/users/check-email").param("email", "fit@example.com"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.available").value(false));
    }

    /**
     * 사용 가능한 닉네임 조회 결과가 available 필드로 전달되는지 검증한다.
     */
    @Test
    void checkNicknameReturnsAvailability() throws Exception {
        when(userService.isNicknameAvailable("fitzza")).thenReturn(true);

        mockMvc.perform(get("/api/v1/users/check-nickname").param("nickname", "fitzza"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.available").value(true));
    }

    /**
     * 필수 이메일 쿼리 매개변수 누락이 공통 HTTP 400 응답이 되는지 검증한다.
     */
    @Test
    void checkEmailRejectsMissingParameter() throws Exception {
        mockMvc.perform(get("/api/v1/users/check-email"))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value("INVALID_INPUT"));
    }

    /**
     * JSON 이스케이프가 필요 없는 테스트 입력으로 가입 요청 본문을 만든다.
     */
    private String signupJson(String email, String password, String nickname) {
        return """
                {"email": "%s", "password": "%s", "nickname": "%s"}
                """.formatted(email, password, nickname);
    }
}
