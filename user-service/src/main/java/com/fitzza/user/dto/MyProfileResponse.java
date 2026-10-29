package com.fitzza.user.dto;

import com.fitzza.user.domain.Gender;
import com.fitzza.user.domain.User;
import com.fitzza.user.domain.UserBody;
import com.fitzza.user.domain.UserRole;
import io.swagger.v3.oas.annotations.media.Schema;
import java.util.List;

// 계정 정보와 신체·취향 정보를 한 단계로 펼쳐서 내려준다(이슈 #44).
public record MyProfileResponse(
        String email,
        String nickname,
        @Schema(description = "사용자 역할(USER 또는 ADMIN). 화면 표시용이며 권한 검사는 서버가 한다", example = "USER")
                UserRole role,
        Gender gender,
        Float height,
        Float weight,
        Integer shoeSize,
        String preferredFit,
        List<String> preferredStyles) {

    public static MyProfileResponse of(User user, UserBody body) {
        return new MyProfileResponse(
                user.getEmail(),
                user.getNickname(),
                user.getRole(),
                body.getGender(),
                body.getHeight(),
                body.getWeight(),
                body.getShoeSize(),
                body.getPreferredFit(),
                body.getPreferredStyles());
    }
}
