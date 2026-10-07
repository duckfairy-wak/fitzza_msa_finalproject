package com.fitzza.user.dto;

import com.fitzza.user.domain.Gender;
import com.fitzza.user.domain.UserBody;
import java.util.List;

public record UserBodyResponse(
        Float height,
        Float weight,
        Gender gender,
        String bodyType,
        String preferredFit,
        List<String> preferredStyles,
        Integer shoeSize) {

    public static UserBodyResponse from(UserBody body) {
        return new UserBodyResponse(
                body.getHeight(),
                body.getWeight(),
                body.getGender(),
                body.getBodyType(),
                body.getPreferredFit(),
                body.getPreferredStyles(),
                body.getShoeSize());
    }
}
