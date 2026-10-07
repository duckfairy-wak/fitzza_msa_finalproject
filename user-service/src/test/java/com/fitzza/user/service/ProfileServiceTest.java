package com.fitzza.user.service;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.AdditionalAnswers.returnsFirstArg;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.fitzza.user.domain.FieldChange;
import com.fitzza.user.domain.Gender;
import com.fitzza.user.domain.User;
import com.fitzza.user.domain.UserBody;
import com.fitzza.user.domain.UserBodyUpdate;
import com.fitzza.user.dto.MyProfileResponse;
import com.fitzza.user.dto.NicknameResponse;
import com.fitzza.user.dto.ProfileOptionsResponse;
import com.fitzza.user.dto.UserBodyResponse;
import com.fitzza.user.exception.ErrorCode;
import com.fitzza.user.exception.UserApiException;
import com.fitzza.user.repository.UserBodyRepository;
import com.fitzza.user.repository.UserRepository;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.stream.LongStream;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.test.util.ReflectionTestUtils;

@ExtendWith(MockitoExtension.class)
class ProfileServiceTest {

    private static final Long USER_ID = 7L;

    @Mock
    private UserRepository userRepository;

    @Mock
    private UserBodyRepository userBodyRepository;

    private ProfileService profileService;

    @BeforeEach
    void setUp() {
        profileService = new ProfileService(userRepository, userBodyRepository);
    }

    @Test
    void optionsExposeEveryCodeWithItsLabel() {
        ProfileOptionsResponse options = profileService.getOptions();

        assertThat(options.bodyTypes()).extracting("code").contains("SLIM", "STANDARD", "MUSCULAR", "CHUBBY");
        assertThat(options.fits())
                .extracting("code")
                .containsExactly("REGULAR", "RELAXED", "SLIM", "OVERSIZED", "CROPPED");
        assertThat(options.styles()).extracting("code").contains("CASUAL", "MINIMAL");
        assertThat(options.fits()).extracting("label").doesNotContainNull();
    }

    @Test
    void myProfileCombinesAccountAndBodyInformation() {
        when(userRepository.findById(USER_ID)).thenReturn(Optional.of(storedUser(USER_ID, "fitzza")));
        when(userBodyRepository.findById(USER_ID)).thenReturn(Optional.of(filledBody()));

        MyProfileResponse profile = profileService.getMyProfile(USER_ID);

        assertThat(profile.email()).isEqualTo("fit@example.com");
        assertThat(profile.nickname()).isEqualTo("fitzza");
        assertThat(profile.body().height()).isEqualTo(172.5f);
        assertThat(profile.body().preferredStyles()).containsExactly("CASUAL", "MINIMAL");
    }

    @Test
    void myProfileReturnsEmptyBodyWhenNothingWasEntered() {
        when(userRepository.findById(USER_ID)).thenReturn(Optional.of(storedUser(USER_ID, "fitzza")));
        when(userBodyRepository.findById(USER_ID)).thenReturn(Optional.of(UserBody.emptyFor(USER_ID)));

        UserBodyResponse body = profileService.getMyProfile(USER_ID).body();

        assertThat(body.height()).isNull();
        assertThat(body.gender()).isNull();
        assertThat(body.preferredStyles()).isEmpty();
    }

    @Test
    void myProfileCreatesBodyRowWhenItIsMissing() {
        when(userRepository.findById(USER_ID)).thenReturn(Optional.of(storedUser(USER_ID, "fitzza")));
        when(userBodyRepository.findById(USER_ID)).thenReturn(Optional.empty());
        when(userBodyRepository.save(any(UserBody.class))).then(returnsFirstArg());

        MyProfileResponse profile = profileService.getMyProfile(USER_ID);

        verify(userBodyRepository).save(any(UserBody.class));
        assertThat(profile.body().height()).isNull();
    }

    @Test
    void myProfileRejectsUnknownUser() {
        when(userRepository.findById(USER_ID)).thenReturn(Optional.empty());

        assertThatThrownBy(() -> profileService.getMyProfile(USER_ID))
                .isInstanceOf(UserApiException.class)
                .extracting("errorCode")
                .isEqualTo(ErrorCode.USER_NOT_FOUND);
    }

    @Test
    void updateChangesSentFieldsClearsNullFieldsAndKeepsTheRest() {
        when(userRepository.existsById(USER_ID)).thenReturn(true);
        when(userBodyRepository.findById(USER_ID)).thenReturn(Optional.of(filledBody()));
        UserBodyUpdate update = new UserBodyUpdate(
                FieldChange.of(180f),
                FieldChange.of(null),
                FieldChange.absent(),
                FieldChange.absent(),
                FieldChange.absent(),
                FieldChange.of(List.of("STREET")),
                FieldChange.absent());

        UserBodyResponse body = profileService.updateMyBody(USER_ID, update);

        assertThat(body.height()).isEqualTo(180f);
        assertThat(body.weight()).isNull();
        assertThat(body.gender()).isEqualTo(Gender.W);
        assertThat(body.bodyType()).isEqualTo("STANDARD");
        assertThat(body.preferredFit()).isEqualTo("OVERSIZED");
        assertThat(body.preferredStyles()).containsExactly("STREET");
        assertThat(body.shoeSize()).isEqualTo(245);
    }

    @Test
    void updateClearsStylesWhenEmptyListIsSent() {
        when(userRepository.existsById(USER_ID)).thenReturn(true);
        when(userBodyRepository.findById(USER_ID)).thenReturn(Optional.of(filledBody()));
        UserBodyUpdate update = new UserBodyUpdate(
                FieldChange.absent(),
                FieldChange.absent(),
                FieldChange.absent(),
                FieldChange.absent(),
                FieldChange.absent(),
                FieldChange.of(List.of()),
                FieldChange.absent());

        UserBodyResponse body = profileService.updateMyBody(USER_ID, update);

        assertThat(body.preferredStyles()).isEmpty();
        assertThat(body.height()).isEqualTo(172.5f);
    }

    @Test
    void updateRejectsUnknownUserWithoutTouchingBody() {
        when(userRepository.existsById(USER_ID)).thenReturn(false);

        assertThatThrownBy(() -> profileService.updateMyBody(USER_ID, noChange()))
                .isInstanceOf(UserApiException.class)
                .extracting("errorCode")
                .isEqualTo(ErrorCode.USER_NOT_FOUND);
        verify(userBodyRepository, never()).findById(USER_ID);
    }

    @Test
    void filledBodyFieldsOmitEverythingThatWasNotEntered() {
        when(userRepository.existsById(USER_ID)).thenReturn(true);
        UserBody body = UserBody.emptyFor(USER_ID);
        body.apply(new UserBodyUpdate(
                FieldChange.of(172.5f),
                FieldChange.absent(),
                FieldChange.absent(),
                FieldChange.absent(),
                FieldChange.of("OVERSIZED"),
                FieldChange.absent(),
                FieldChange.absent()));
        when(userBodyRepository.findById(USER_ID)).thenReturn(Optional.of(body));

        Map<String, Object> filled = profileService.getFilledBodyFields(USER_ID);

        assertThat(filled).containsOnlyKeys("height", "preferredFit");
        assertThat(filled).containsEntry("height", 172.5f).containsEntry("preferredFit", "OVERSIZED");
    }

    @Test
    void nicknamesAreReturnedOnlyForUsersThatExist() {
        when(userRepository.findAllById(List.of(7L, 8L, 999L)))
                .thenReturn(List.of(storedUser(7L, "fitzza"), storedUser(8L, "민준")));

        List<NicknameResponse> nicknames = profileService.findNicknames(List.of(7L, 8L, 999L));

        assertThat(nicknames).containsExactly(new NicknameResponse(7L, "fitzza"), new NicknameResponse(8L, "민준"));
    }

    @Test
    void nicknameLookupRejectsEmptyOrOversizedRequest() {
        List<Long> tooMany = LongStream.rangeClosed(1, ProfileService.MAX_NICKNAME_LOOKUP_SIZE + 1)
                .boxed()
                .toList();

        assertThatThrownBy(() -> profileService.findNicknames(List.of()))
                .isInstanceOf(UserApiException.class)
                .extracting("errorCode")
                .isEqualTo(ErrorCode.INVALID_INPUT);
        assertThatThrownBy(() -> profileService.findNicknames(tooMany))
                .isInstanceOf(UserApiException.class)
                .extracting("errorCode")
                .isEqualTo(ErrorCode.INVALID_INPUT);
    }

    private User storedUser(Long id, String nickname) {
        User user = User.create("fit@example.com", "ENCODED", nickname);
        ReflectionTestUtils.setField(user, "id", id);
        return user;
    }

    private UserBody filledBody() {
        UserBody body = UserBody.emptyFor(USER_ID);
        body.apply(new UserBodyUpdate(
                FieldChange.of(172.5f),
                FieldChange.of(64f),
                FieldChange.of(Gender.W),
                FieldChange.of("STANDARD"),
                FieldChange.of("OVERSIZED"),
                FieldChange.of(List.of("CASUAL", "MINIMAL")),
                FieldChange.of(245)));
        return body;
    }

    private UserBodyUpdate noChange() {
        return new UserBodyUpdate(
                FieldChange.absent(),
                FieldChange.absent(),
                FieldChange.absent(),
                FieldChange.absent(),
                FieldChange.absent(),
                FieldChange.absent(),
                FieldChange.absent());
    }
}
