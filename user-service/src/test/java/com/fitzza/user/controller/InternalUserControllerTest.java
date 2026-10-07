package com.fitzza.user.controller;

import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.fitzza.user.dto.NicknameResponse;
import com.fitzza.user.exception.ErrorCode;
import com.fitzza.user.exception.GlobalExceptionHandler;
import com.fitzza.user.exception.UserApiException;
import com.fitzza.user.service.ProfileService;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

class InternalUserControllerTest {

    private final ProfileService profileService = mock(ProfileService.class);
    private MockMvc mockMvc;

    @BeforeEach
    void setUp() {
        mockMvc = MockMvcBuilders.standaloneSetup(new InternalUserController(profileService))
                .setControllerAdvice(new GlobalExceptionHandler())
                .build();
    }

    @Test
    void nicknamesAreLookedUpFromCommaSeparatedIds() throws Exception {
        when(profileService.findNicknames(List.of(7L, 8L)))
                .thenReturn(List.of(new NicknameResponse(7L, "fitzza"), new NicknameResponse(8L, "newbie")));

        mockMvc.perform(get("/internal/users").param("userIds", "7,8"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$[0].userId").value(7))
                .andExpect(jsonPath("$[0].nickname").value("fitzza"))
                .andExpect(jsonPath("$[1].nickname").value("newbie"));
    }

    @Test
    void nicknameLookupRejectsNonNumericId() throws Exception {
        mockMvc.perform(get("/internal/users").param("userIds", "7,abc"))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value("INVALID_INPUT"));
    }

    @Test
    void bodyLookupReturnsOnlyFilledFields() throws Exception {
        when(profileService.getFilledBodyFields(7L)).thenReturn(Map.of("height", 172.5f));

        mockMvc.perform(get("/internal/users/7/body"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.height").value(172.5))
                .andExpect(jsonPath("$.weight").doesNotExist());
    }

    @Test
    void bodyLookupReturnsNotFoundForUnknownUser() throws Exception {
        when(profileService.getFilledBodyFields(999L)).thenThrow(new UserApiException(ErrorCode.USER_NOT_FOUND));

        mockMvc.perform(get("/internal/users/999/body"))
                .andExpect(status().isNotFound())
                .andExpect(jsonPath("$.code").value("USER_NOT_FOUND"));
    }
}
