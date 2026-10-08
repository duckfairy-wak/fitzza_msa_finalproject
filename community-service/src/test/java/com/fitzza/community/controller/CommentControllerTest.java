package com.fitzza.community.controller;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.doThrow;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.delete;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.patch;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.fitzza.community.dto.AuthorResponse;
import com.fitzza.community.dto.CommentCreateRequest;
import com.fitzza.community.dto.CommentCreatedResponse;
import com.fitzza.community.dto.CommentResponse;
import com.fitzza.community.dto.CommentUpdateRequest;
import com.fitzza.community.dto.LikeCountResponse;
import com.fitzza.community.exception.CommunityApiException;
import com.fitzza.community.exception.ErrorCode;
import com.fitzza.community.exception.GlobalExceptionHandler;
import com.fitzza.community.service.CommentService;
import java.util.List;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

class CommentControllerTest {

    private static final String USER_ID_HEADER = "X-User-Id";
    private static final String POST_COMMENTS = "/api/v1/community/posts/3/comments";
    private static final String COMMENTS = "/api/v1/community/comments";

    private final CommentService commentService = mock(CommentService.class);
    private MockMvc mockMvc;

    @BeforeEach
    void setUp() {
        mockMvc = MockMvcBuilders.standaloneSetup(new CommentController(commentService))
                .setControllerAdvice(new GlobalExceptionHandler())
                .build();
    }

    @Test
    void listIsPublicAndReturnsRepliesUnderTheirComment() throws Exception {
        CommentResponse reply =
                new CommentResponse(2L, "답글", new AuthorResponse(8L, "coordi"), 0, false, false, null, List.of());
        CommentResponse deletedParent =
                new CommentResponse(1L, "삭제된 댓글입니다", null, 0, false, true, null, List.of(reply));
        when(commentService.getComments(3L, null)).thenReturn(List.of(deletedParent));

        mockMvc.perform(get(POST_COMMENTS))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$[0].commentId").value(1))
                .andExpect(jsonPath("$[0].isDeleted").value(true))
                .andExpect(jsonPath("$[0].deleted").doesNotExist())
                .andExpect(jsonPath("$[0].author").doesNotExist())
                .andExpect(jsonPath("$[0].replies[0].commentId").value(2))
                .andExpect(jsonPath("$[0].replies[0].isDeleted").value(false))
                .andExpect(jsonPath("$[0].replies[0].author.nickname").value("coordi"));
    }

    @Test
    void listPassesTheViewerWhenLoggedIn() throws Exception {
        when(commentService.getComments(3L, 8L)).thenReturn(List.of());

        mockMvc.perform(get(POST_COMMENTS).header(USER_ID_HEADER, "8")).andExpect(status().isOk());
        verify(commentService).getComments(3L, 8L);
    }

    @Test
    void createReturnsCreatedWithTheCommentId() throws Exception {
        when(commentService.create(eq(7L), eq(3L), any(CommentCreateRequest.class)))
                .thenReturn(new CommentCreatedResponse(11L));

        mockMvc.perform(post(POST_COMMENTS)
                        .header(USER_ID_HEADER, "7")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"content\":\"잘 어울려요\",\"parentCommentId\":5}"))
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.commentId").value(11));

        ArgumentCaptor<CommentCreateRequest> captor = ArgumentCaptor.forClass(CommentCreateRequest.class);
        verify(commentService).create(eq(7L), eq(3L), captor.capture());
        assertThat(captor.getValue().content()).isEqualTo("잘 어울려요");
        assertThat(captor.getValue().parentCommentId()).isEqualTo(5L);
    }

    @Test
    void createRequiresTheUserHeader() throws Exception {
        mockMvc.perform(post(POST_COMMENTS)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"content\":\"댓글\"}"))
                .andExpect(status().isUnauthorized())
                .andExpect(jsonPath("$.code").value("UNAUTHENTICATED"));
        verifyNoInteractions(commentService);
    }

    @Test
    void createRejectsBlankComment() throws Exception {
        mockMvc.perform(post(POST_COMMENTS)
                        .header(USER_ID_HEADER, "7")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"content\":\"  \"}"))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.message").value("댓글 내용을 입력해주세요."));
        verifyNoInteractions(commentService);
    }

    @Test
    void createRejectsCommentLongerThanFiveHundredCharacters() throws Exception {
        String tooLong = "가".repeat(501);

        mockMvc.perform(post(POST_COMMENTS)
                        .header(USER_ID_HEADER, "7")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"content\":\"" + tooLong + "\"}"))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.message").value("댓글은 500자 이하로 입력해주세요."));
        verifyNoInteractions(commentService);
    }

    @Test
    void createOnMissingPostIsNotFound() throws Exception {
        when(commentService.create(eq(7L), eq(3L), any(CommentCreateRequest.class)))
                .thenThrow(new CommunityApiException(ErrorCode.POST_NOT_FOUND));

        mockMvc.perform(post(POST_COMMENTS)
                        .header(USER_ID_HEADER, "7")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"content\":\"댓글\"}"))
                .andExpect(status().isNotFound())
                .andExpect(jsonPath("$.code").value("POST_NOT_FOUND"));
    }

    @Test
    void updatePassesTheNewContent() throws Exception {
        mockMvc.perform(patch(COMMENTS + "/11")
                        .header(USER_ID_HEADER, "7")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"content\":\"고친 내용\"}"))
                .andExpect(status().isOk());

        ArgumentCaptor<CommentUpdateRequest> captor = ArgumentCaptor.forClass(CommentUpdateRequest.class);
        verify(commentService).update(eq(7L), eq(11L), captor.capture());
        assertThat(captor.getValue().content()).isEqualTo("고친 내용");
    }

    @Test
    void updateByAnotherUserIsForbidden() throws Exception {
        doThrow(new CommunityApiException(ErrorCode.NOT_AUTHOR))
                .when(commentService)
                .update(eq(8L), eq(11L), any(CommentUpdateRequest.class));

        mockMvc.perform(patch(COMMENTS + "/11")
                        .header(USER_ID_HEADER, "8")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"content\":\"남의 댓글\"}"))
                .andExpect(status().isForbidden())
                .andExpect(jsonPath("$.code").value("NOT_AUTHOR"));
    }

    @Test
    void deleteReturnsNoContent() throws Exception {
        mockMvc.perform(delete(COMMENTS + "/11").header(USER_ID_HEADER, "7")).andExpect(status().isNoContent());
        verify(commentService).delete(7L, 11L);
    }

    @Test
    void deleteRequiresTheUserHeader() throws Exception {
        mockMvc.perform(delete(COMMENTS + "/11")).andExpect(status().isUnauthorized());
        verifyNoInteractions(commentService);
    }

    @Test
    void likeAndUnlikeReturnTheCurrentCount() throws Exception {
        when(commentService.like(8L, 11L)).thenReturn(new LikeCountResponse(2));
        when(commentService.unlike(8L, 11L)).thenReturn(new LikeCountResponse(1));

        mockMvc.perform(post(COMMENTS + "/11/likes").header(USER_ID_HEADER, "8"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.likeCount").value(2));
        mockMvc.perform(delete(COMMENTS + "/11/likes").header(USER_ID_HEADER, "8"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.likeCount").value(1));
    }
}
