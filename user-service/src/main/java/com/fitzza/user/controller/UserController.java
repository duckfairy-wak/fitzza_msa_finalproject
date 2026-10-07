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

    public UserController(UserService userService) {
        this.userService = userService;
    }

    @PostMapping("/signup")
    @ResponseStatus(HttpStatus.CREATED)
    public SignupResponse signUp(@Valid @RequestBody SignupRequest request) {
        return new SignupResponse(userService.signUp(request));
    }

    @GetMapping("/check-email")
    public AvailabilityResponse checkEmail(@RequestParam("email") String email) {
        return new AvailabilityResponse(userService.isEmailAvailable(email));
    }

    @GetMapping("/check-nickname")
    public AvailabilityResponse checkNickname(@RequestParam("nickname") String nickname) {
        return new AvailabilityResponse(userService.isNicknameAvailable(nickname));
    }
}
