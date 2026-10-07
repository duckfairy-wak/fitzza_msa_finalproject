package com.fitzza.user.dto;

import com.fitzza.user.domain.User;
import jakarta.validation.constraints.Email;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Pattern;
import jakarta.validation.constraints.Size;

public record SignupRequest(
        @NotBlank(message = "이메일을 입력해주세요.")
        @Email(regexp = User.EMAIL_REGEX, message = "이메일 형식이 올바르지 않습니다.")
        @Size(max = 255, message = "이메일은 255자 이하여야 합니다.")
        String email,

        @NotBlank(message = "비밀번호를 입력해주세요.")
        @Pattern(
                regexp = "^(?=.*[A-Za-z])(?=.*\\d)[A-Za-z\\d]{8,24}$",
                message = "비밀번호는 영문과 숫자를 모두 포함한 8~24자여야 하며 특수문자는 쓸 수 없습니다.")
        String password,

        @NotBlank(message = "닉네임을 입력해주세요.")
        @Pattern(regexp = User.NICKNAME_REGEX, message = "닉네임은 한글·영문·숫자 2~10자여야 하며 공백과 특수문자는 쓸 수 없습니다.")
        String nickname) {
}
