package com.fitzza.community.controller;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.fitzza.community.domain.VoteItemType;
import com.fitzza.community.domain.VoteOptionSource;
import com.fitzza.community.dto.VoteCastResponse;
import com.fitzza.community.dto.VoteClosedResponse;
import com.fitzza.community.dto.VoteOptionResult;
import com.fitzza.community.dto.VotePostCreateRequest;
import com.fitzza.community.dto.VotePostCreatedResponse;
import com.fitzza.community.dto.VoteResultResponse;
import com.fitzza.community.exception.CommunityApiException;
import com.fitzza.community.exception.ErrorCode;
import com.fitzza.community.exception.GlobalExceptionHandler;
import com.fitzza.community.service.VoteService;
import java.util.List;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

class VoteControllerTest {

    private static final String USER_ID_HEADER = "X-User-Id";
    private static final String POSTS = "/api/v1/community/posts";
    private static final String TWO_OPTIONS = "["
            + "{\"source\":\"WISHLIST\",\"itemType\":\"PRODUCT\",\"itemId\":\"55\","
            + "\"imageUrl\":\"https://cdn.example.com/a.png\"},"
            + "{\"source\":\"UPLOAD\",\"itemType\":\"IMAGE\",\"imageUrl\":\"https://cdn.example.com/b.png\"}"
            + "]";

    private final VoteService voteService = mock(VoteService.class);
    private MockMvc mockMvc;

    @BeforeEach
    void setUp() {
        mockMvc = MockMvcBuilders.standaloneSetup(new VoteController(voteService))
                .setControllerAdvice(new GlobalExceptionHandler())
                .build();
    }

    @Test
    void createReturnsCreatedAndPassesTheOptionsInOrder() throws Exception {
        when(voteService.createVotePost(eq(7L), any(VotePostCreateRequest.class)))
                .thenReturn(new VotePostCreatedResponse(3L, null));

        mockMvc.perform(post(POSTS + "/vote")
                        .header(USER_ID_HEADER, "7")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(votePostBody(TWO_OPTIONS)))
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.postId").value(3));

        ArgumentCaptor<VotePostCreateRequest> captor = ArgumentCaptor.forClass(VotePostCreateRequest.class);
        verify(voteService).createVotePost(eq(7L), captor.capture());
        assertThat(captor.getValue().options()).hasSize(2);
        assertThat(captor.getValue().options().get(0).source()).isEqualTo(VoteOptionSource.WISHLIST);
        assertThat(captor.getValue().options().get(0).itemId()).isEqualTo("55");
        assertThat(captor.getValue().options().get(1).itemType()).isEqualTo(VoteItemType.IMAGE);
        assertThat(captor.getValue().options().get(1).itemId()).isNull();
    }

    @Test
    void createRejectsFewerThanTwoOptions() throws Exception {
        String oneOption = "[{\"source\":\"UPLOAD\",\"itemType\":\"IMAGE\","
                + "\"imageUrl\":\"https://cdn.example.com/b.png\"}]";

        mockMvc.perform(post(POSTS + "/vote")
                        .header(USER_ID_HEADER, "7")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(votePostBody(oneOption)))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value("INVALID_INPUT"));
        verifyNoInteractions(voteService);
    }

    @Test
    void createRejectsAnOptionWithoutAnImage() throws Exception {
        String missingImage = "[{\"source\":\"UPLOAD\",\"itemType\":\"IMAGE\"},"
                + "{\"source\":\"UPLOAD\",\"itemType\":\"IMAGE\",\"imageUrl\":\"https://cdn.example.com/b.png\"}]";

        mockMvc.perform(post(POSTS + "/vote")
                        .header(USER_ID_HEADER, "7")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(votePostBody(missingImage)))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value("INVALID_INPUT"));
        verifyNoInteractions(voteService);
    }

    @Test
    void createRequiresTheUserHeader() throws Exception {
        mockMvc.perform(post(POSTS + "/vote")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(votePostBody(TWO_OPTIONS)))
                .andExpect(status().isUnauthorized());
        verifyNoInteractions(voteService);
    }

    @Test
    void votePassesTheChosenOption() throws Exception {
        when(voteService.vote(8L, 3L, 100L)).thenReturn(new VoteCastResponse(100L));

        mockMvc.perform(post(POSTS + "/3/votes")
                        .header(USER_ID_HEADER, "8")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"voteOptionId\":100}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.voteOptionId").value(100));
    }

    @Test
    void voteOnAClosedVoteIsAConflict() throws Exception {
        when(voteService.vote(8L, 3L, 100L)).thenThrow(new CommunityApiException(ErrorCode.VOTE_CLOSED));

        mockMvc.perform(post(POSTS + "/3/votes")
                        .header(USER_ID_HEADER, "8")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"voteOptionId\":100}"))
                .andExpect(status().isConflict())
                .andExpect(jsonPath("$.code").value("VOTE_CLOSED"));
    }

    @Test
    void voteRequiresAnOptionAndTheUserHeader() throws Exception {
        mockMvc.perform(post(POSTS + "/3/votes")
                        .header(USER_ID_HEADER, "8")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{}"))
                .andExpect(status().isBadRequest());
        mockMvc.perform(post(POSTS + "/3/votes")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"voteOptionId\":100}"))
                .andExpect(status().isUnauthorized());
        verifyNoInteractions(voteService);
    }

    @Test
    void resultsArePublicAndIncludeTheViewerChoiceWhenLoggedIn() throws Exception {
        when(voteService.getResults(3L, null)).thenReturn(sampleResults(null));
        when(voteService.getResults(3L, 8L)).thenReturn(sampleResults(100L));

        mockMvc.perform(get(POSTS + "/3/votes"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.total").value(3))
                .andExpect(jsonPath("$.closed").value(false))
                .andExpect(jsonPath("$.options[0].label").value("A"))
                .andExpect(jsonPath("$.options[0].count").value(3))
                .andExpect(jsonPath("$.myVoteOptionId").doesNotExist());
        mockMvc.perform(get(POSTS + "/3/votes").header(USER_ID_HEADER, "8"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.myVoteOptionId").value(100));
    }

    @Test
    void closeReturnsTheClosedStateAndIsForbiddenForOthers() throws Exception {
        when(voteService.close(7L, 3L)).thenReturn(new VoteClosedResponse(true));
        when(voteService.close(8L, 3L)).thenThrow(new CommunityApiException(ErrorCode.NOT_AUTHOR));

        mockMvc.perform(post(POSTS + "/3/votes/close").header(USER_ID_HEADER, "7"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.closed").value(true));
        mockMvc.perform(post(POSTS + "/3/votes/close").header(USER_ID_HEADER, "8"))
                .andExpect(status().isForbidden())
                .andExpect(jsonPath("$.code").value("NOT_AUTHOR"));
    }

    private static String votePostBody(String options) {
        return "{\"title\":\"뭐가 나을까요\",\"content\":\"골라주세요\",\"category\":\"COORDI_QUESTION\",\"options\":"
                + options + "}";
    }

    private static VoteResultResponse sampleResults(Long myVoteOptionId) {
        return new VoteResultResponse(
                List.of(new VoteOptionResult(100L, "A", 3, 1.0), new VoteOptionResult(101L, "B", 0, 0.0)),
                3,
                null,
                false,
                myVoteOptionId);
    }
}
