package com.fitzza.user.controller;

import com.fitzza.user.dto.NicknameResponse;
import com.fitzza.user.service.ProfileService;
import java.util.List;
import java.util.Map;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

// 다른 서비스만 호출하는 API. 게이트웨이 라우트에 올리지 않는다.
@RestController
@RequestMapping("/internal/users")
public class InternalUserController {

    private final ProfileService profileService;

    public InternalUserController(ProfileService profileService) {
        this.profileService = profileService;
    }

    @GetMapping
    public List<NicknameResponse> findNicknames(@RequestParam("userIds") List<Long> userIds) {
        return profileService.findNicknames(userIds);
    }

    @GetMapping("/{userId}/body")
    public Map<String, Object> getFilledBodyFields(@PathVariable("userId") Long userId) {
        return profileService.getFilledBodyFields(userId);
    }
}
