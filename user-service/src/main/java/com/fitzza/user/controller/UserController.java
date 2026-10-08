package com.fitzza.user.controller;

import com.fitzza.user.dto.AvailabilityResponse;
import com.fitzza.user.dto.SignupRequest;
import com.fitzza.user.dto.SignupResponse;
import com.fitzza.user.service.UserService;
import jakarta.validation.Valid;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.ResponseStatus;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/v1/users")
public class UserController {

    private final UserService userService;

    /**
     * 가입 및 중복 확인 요청을 처리할 사용자 서비스를 주입한다.
     */
    public UserController(UserService userService) {
        this.userService = userService;
    }

    /**
     * 검증된 가입 요청을 처리하고 생성된 사용자 ID를 HTTP 201 응답으로 반환한다.
     */
    @PostMapping("/signup")
    @ResponseStatus(HttpStatus.CREATED)
    public SignupResponse signUp(@Valid @RequestBody SignupRequest request) {
        return new SignupResponse(userService.signUp(request));
    }

    /**
     * 이메일 형식을 검사한 뒤 정규화된 주소의 사용 가능 여부를 반환한다.
     */
    @GetMapping("/check-email")
    public AvailabilityResponse checkEmail(@RequestParam("email") String email) {
        return new AvailabilityResponse(userService.isEmailAvailable(email));
    }

    /**
     * 닉네임 형식을 검사한 뒤 사용 가능 여부를 반환한다.
     */
    @GetMapping("/check-nickname")
    public AvailabilityResponse checkNickname(@RequestParam("nickname") String nickname) {
        return new AvailabilityResponse(userService.isNicknameAvailable(nickname));
    }
}
