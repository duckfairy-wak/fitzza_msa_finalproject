package com.fitzza.user.service;

import com.fitzza.user.domain.BodyType;
import com.fitzza.user.domain.FitType;
import com.fitzza.user.domain.StyleTag;
import com.fitzza.user.domain.User;
import com.fitzza.user.domain.UserBody;
import com.fitzza.user.domain.UserBodyUpdate;
import com.fitzza.user.dto.MyProfileResponse;
import com.fitzza.user.dto.NicknameResponse;
import com.fitzza.user.dto.OptionResponse;
import com.fitzza.user.dto.ProfileOptionsResponse;
import com.fitzza.user.dto.UserBodyResponse;
import com.fitzza.user.exception.ErrorCode;
import com.fitzza.user.exception.UserApiException;
import com.fitzza.user.repository.UserBodyRepository;
import com.fitzza.user.repository.UserRepository;
import java.util.Arrays;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class ProfileService {

    static final int MAX_NICKNAME_LOOKUP_SIZE = 100;

    private final UserRepository userRepository;
    private final UserBodyRepository userBodyRepository;

    public ProfileService(UserRepository userRepository, UserBodyRepository userBodyRepository) {
        this.userRepository = userRepository;
        this.userBodyRepository = userBodyRepository;
    }

    public ProfileOptionsResponse getOptions() {
        return new ProfileOptionsResponse(
                Arrays.stream(BodyType.values())
                        .map(type -> new OptionResponse(type.name(), type.getLabel()))
                        .toList(),
                Arrays.stream(FitType.values())
                        .map(type -> new OptionResponse(type.name(), type.getLabel()))
                        .toList(),
                Arrays.stream(StyleTag.values())
                        .map(tag -> new OptionResponse(tag.name(), tag.getLabel()))
                        .toList());
    }

    @Transactional
    public MyProfileResponse getMyProfile(Long userId) {
        User user = userRepository.findById(userId)
                .orElseThrow(() -> new UserApiException(ErrorCode.USER_NOT_FOUND));
        return new MyProfileResponse(
                user.getEmail(), user.getNickname(), UserBodyResponse.from(findOrCreateBody(userId)));
    }

    @Transactional
    public UserBodyResponse updateMyBody(Long userId, UserBodyUpdate update) {
        requireExistingUser(userId);
        UserBody body = findOrCreateBody(userId);
        body.apply(update);
        return UserBodyResponse.from(body);
    }

    // 추천 서비스는 입력된 항목만 개인화 조건으로 쓰므로 비어 있는 항목은 키 자체를 내보내지 않는다.
    @Transactional
    public Map<String, Object> getFilledBodyFields(Long userId) {
        requireExistingUser(userId);
        UserBody body = findOrCreateBody(userId);

        Map<String, Object> filled = new LinkedHashMap<>();
        putIfPresent(filled, "height", body.getHeight());
        putIfPresent(filled, "weight", body.getWeight());
        putIfPresent(filled, "gender", body.getGender());
        putIfPresent(filled, "bodyType", body.getBodyType());
        putIfPresent(filled, "preferredFit", body.getPreferredFit());
        if (!body.getPreferredStyles().isEmpty()) {
            filled.put("preferredStyles", body.getPreferredStyles());
        }
        putIfPresent(filled, "shoeSize", body.getShoeSize());
        return filled;
    }

    @Transactional(readOnly = true)
    public List<NicknameResponse> findNicknames(List<Long> userIds) {
        if (userIds.isEmpty() || userIds.size() > MAX_NICKNAME_LOOKUP_SIZE) {
            throw new UserApiException(
                    ErrorCode.INVALID_INPUT, "userIds는 1~" + MAX_NICKNAME_LOOKUP_SIZE + "개여야 합니다.");
        }
        return userRepository.findAllById(userIds).stream()
                .map(user -> new NicknameResponse(user.getId(), user.getNickname()))
                .toList();
    }

    private void requireExistingUser(Long userId) {
        if (!userRepository.existsById(userId)) {
            throw new UserApiException(ErrorCode.USER_NOT_FOUND);
        }
    }

    // 가입 때 빈 행을 만들지만, 그 전에 만들어진 계정이나 누락된 경우에도 같은 흐름으로 동작하게 한다.
    private UserBody findOrCreateBody(Long userId) {
        return userBodyRepository.findById(userId)
                .orElseGet(() -> userBodyRepository.save(UserBody.emptyFor(userId)));
    }

    private void putIfPresent(Map<String, Object> target, String key, Object value) {
        if (value != null) {
            target.put(key, value);
        }
    }
}
