package com.fitzza.user.controller;

import com.fasterxml.jackson.databind.JsonNode;
import com.fitzza.user.dto.MyProfileResponse;
import com.fitzza.user.dto.ProfileOptionsResponse;
import com.fitzza.user.dto.UserBodyResponse;
import com.fitzza.user.security.AuthHeaders;
import com.fitzza.user.service.ProfileService;
import com.fitzza.user.service.UserBodyUpdateParser;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PatchMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/v1/users")
public class ProfileController {

    private final ProfileService profileService;
    private final UserBodyUpdateParser userBodyUpdateParser;

    public ProfileController(ProfileService profileService, UserBodyUpdateParser userBodyUpdateParser) {
        this.profileService = profileService;
        this.userBodyUpdateParser = userBodyUpdateParser;
    }

    @GetMapping("/profile/options")
    public ProfileOptionsResponse getProfileOptions() {
        return profileService.getOptions();
    }

    @GetMapping("/me")
    public MyProfileResponse getMyProfile(@RequestHeader(AuthHeaders.USER_ID) Long userId) {
        return profileService.getMyProfile(userId);
    }

    @PatchMapping("/me/body")
    public UserBodyResponse updateMyBody(
            @RequestHeader(AuthHeaders.USER_ID) Long userId, @RequestBody JsonNode body) {
        return profileService.updateMyBody(userId, userBodyUpdateParser.parse(body));
    }
}
