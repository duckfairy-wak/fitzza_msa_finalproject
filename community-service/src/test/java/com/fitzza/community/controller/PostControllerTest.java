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

import com.fitzza.community.domain.PostCategory;
import com.fitzza.community.domain.PostType;
import com.fitzza.community.dto.AuthorResponse;
import com.fitzza.community.dto.LikeCountResponse;
import com.fitzza.community.dto.PostCreateRequest;
import com.fitzza.community.dto.PostCreatedResponse;
import com.fitzza.community.dto.PostDetailResponse;
import com.fitzza.community.dto.PostPageResponse;
import com.fitzza.community.dto.PostSummaryResponse;
import com.fitzza.community.dto.PostUpdateRequest;
import com.fitzza.community.exception.CommunityApiException;
import com.fitzza.community.exception.ErrorCode;
import com.fitzza.community.exception.GlobalExceptionHandler;
import com.fitzza.community.service.PostService;
import java.util.List;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.dao.OptimisticLockingFailureException;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

class PostControllerTest {

    private static final String USER_ID_HEADER = "X-User-Id";
    private static final String POSTS = "/api/v1/community/posts";

    private final PostService postService = mock(PostService.class);
    private MockMvc mockMvc;

    @BeforeEach
    void setUp() {
        mockMvc = MockMvcBuilders.standaloneSetup(new PostController(postService))
                .setControllerAdvice(new GlobalExceptionHandler())
                .build();
    }

    @Test
    void feedIsPublicAndPassesFiltersToTheService() throws Exception {
        when(postService.getFeed(PostCategory.FASHION, PostType.VOTE, "셔츠", 1, 10))
                .thenReturn(new PostPageResponse(
                        List.of(new PostSummaryResponse(
                                3L, "셔츠 골라주세요", PostCategory.FASHION, PostType.VOTE, "fitzza", null, null, 2, 5)),
                        1,
                        4));

        mockMvc.perform(get(POSTS)
                        .param("category", "FASHION")
                        .param("postType", "VOTE")
                        .param("keyword", "셔츠")
                        .param("page", "1")
                        .param("size", "10"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.content[0].postId").value(3))
                .andExpect(jsonPath("$.content[0].nickname").value("fitzza"))
                .andExpect(jsonPath("$.content[0].likeCount").value(2))
                .andExpect(jsonPath("$.content[0].commentCount").value(5))
                .andExpect(jsonPath("$.page").value(1))
                .andExpect(jsonPath("$.totalPages").value(4));
    }

    @Test
    void feedUsesFirstPageOfTwentyByDefault() throws Exception {
        when(postService.getFeed(null, null, null, 0, 20)).thenReturn(new PostPageResponse(List.of(), 0, 0));

        mockMvc.perform(get(POSTS))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.content.length()").value(0));
        verify(postService).getFeed(null, null, null, 0, 20);
    }

    @Test
    void feedRejectsUnknownCategory() throws Exception {
        mockMvc.perform(get(POSTS).param("category", "FOOD"))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value("INVALID_INPUT"));
        verifyNoInteractions(postService);
    }

    @Test
    void detailIsPublicAndPassesNoViewerWithoutLogin() throws Exception {
        when(postService.getDetail(3L, null)).thenReturn(sampleDetail(false));

        mockMvc.perform(get(POSTS + "/3"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.postId").value(3))
                .andExpect(jsonPath("$.author.userId").value(7))
                .andExpect(jsonPath("$.author.nickname").value("fitzza"))
                .andExpect(jsonPath("$.liked").value(false));
    }

    @Test
    void detailPassesTheViewerWhenLoggedIn() throws Exception {
        when(postService.getDetail(3L, 8L)).thenReturn(sampleDetail(true));

        mockMvc.perform(get(POSTS + "/3").header(USER_ID_HEADER, "8"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.liked").value(true));
    }

    @Test
    void detailOfMissingPostIsNotFound() throws Exception {
        when(postService.getDetail(99L, null)).thenThrow(new CommunityApiException(ErrorCode.POST_NOT_FOUND));

        mockMvc.perform(get(POSTS + "/99"))
                .andExpect(status().isNotFound())
                .andExpect(jsonPath("$.code").value("POST_NOT_FOUND"));
    }

    @Test
    void createReturnsCreatedWithThePostId() throws Exception {
        when(postService.create(eq(7L), any(PostCreateRequest.class))).thenReturn(new PostCreatedResponse(3L));

        mockMvc.perform(post(POSTS)
                        .header(USER_ID_HEADER, "7")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"title\":\"오늘의 코디\",\"content\":\"내용\",\"category\":\"DAILY\"}"))
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.postId").value(3));

        ArgumentCaptor<PostCreateRequest> captor = ArgumentCaptor.forClass(PostCreateRequest.class);
        verify(postService).create(eq(7L), captor.capture());
        assertThat(captor.getValue().title()).isEqualTo("오늘의 코디");
        assertThat(captor.getValue().category()).isEqualTo(PostCategory.DAILY);
        assertThat(captor.getValue().imageUrl()).isNull();
    }

    @Test
    void createRequiresTheUserHeader() throws Exception {
        mockMvc.perform(post(POSTS)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"title\":\"제목\",\"content\":\"내용\",\"category\":\"DAILY\"}"))
                .andExpect(status().isUnauthorized())
                .andExpect(jsonPath("$.code").value("UNAUTHENTICATED"));
        verifyNoInteractions(postService);
    }

    @Test
    void createRejectsBlankTitle() throws Exception {
        mockMvc.perform(post(POSTS)
                        .header(USER_ID_HEADER, "7")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"title\":\"   \",\"content\":\"내용\",\"category\":\"DAILY\"}"))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value("INVALID_INPUT"))
                .andExpect(jsonPath("$.message").value("제목을 입력해주세요."));
        verifyNoInteractions(postService);
    }

    @Test
    void createRejectsMissingOrUnknownCategory() throws Exception {
        mockMvc.perform(post(POSTS)
                        .header(USER_ID_HEADER, "7")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"title\":\"제목\",\"content\":\"내용\"}"))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.message").value("분류를 선택해주세요."));

        mockMvc.perform(post(POSTS)
                        .header(USER_ID_HEADER, "7")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"title\":\"제목\",\"content\":\"내용\",\"category\":\"FOOD\"}"))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value("INVALID_INPUT"));
        verifyNoInteractions(postService);
    }

    @Test
    void updateTellsApartAnOmittedImageFromAnImageSetToNull() throws Exception {
        mockMvc.perform(patch(POSTS + "/3")
                        .header(USER_ID_HEADER, "7")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"title\":\"새 제목\"}"))
                .andExpect(status().isOk());
        mockMvc.perform(patch(POSTS + "/4")
                        .header(USER_ID_HEADER, "7")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"imageUrl\":null}"))
                .andExpect(status().isOk());

        ArgumentCaptor<PostUpdateRequest> omitted = ArgumentCaptor.forClass(PostUpdateRequest.class);
        verify(postService).update(eq(7L), eq(3L), omitted.capture());
        assertThat(omitted.getValue().getTitle()).isEqualTo("새 제목");
        assertThat(omitted.getValue().isImageUrlSent()).isFalse();

        ArgumentCaptor<PostUpdateRequest> cleared = ArgumentCaptor.forClass(PostUpdateRequest.class);
        verify(postService).update(eq(7L), eq(4L), cleared.capture());
        assertThat(cleared.getValue().getTitle()).isNull();
        assertThat(cleared.getValue().isImageUrlSent()).isTrue();
        assertThat(cleared.getValue().getImageUrl()).isNull();
    }

    @Test
    void updateRejectsBlankTitle() throws Exception {
        mockMvc.perform(patch(POSTS + "/3")
                        .header(USER_ID_HEADER, "7")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"title\":\"  \"}"))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.message").value("제목을 입력해주세요."));
        verifyNoInteractions(postService);
    }

    @Test
    void updateByAnotherUserIsForbidden() throws Exception {
        doThrow(new CommunityApiException(ErrorCode.NOT_AUTHOR))
                .when(postService)
                .update(eq(8L), eq(3L), any(PostUpdateRequest.class));

        mockMvc.perform(patch(POSTS + "/3")
                        .header(USER_ID_HEADER, "8")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"title\":\"남의 글\"}"))
                .andExpect(status().isForbidden())
                .andExpect(jsonPath("$.code").value("NOT_AUTHOR"));
    }

    @Test
    void deleteReturnsNoContent() throws Exception {
        mockMvc.perform(delete(POSTS + "/3").header(USER_ID_HEADER, "7")).andExpect(status().isNoContent());
        verify(postService).delete(7L, 3L);
    }

    @Test
    void deleteThatLosesToAConcurrentChangeIsAConflict() throws Exception {
        doThrow(new OptimisticLockingFailureException("stale post"))
                .when(postService)
                .delete(7L, 3L);

        mockMvc.perform(delete(POSTS + "/3").header(USER_ID_HEADER, "7"))
                .andExpect(status().isConflict())
                .andExpect(jsonPath("$.code").value("CONCURRENT_UPDATE"));
    }

    @Test
    void deleteRequiresTheUserHeader() throws Exception {
        mockMvc.perform(delete(POSTS + "/3")).andExpect(status().isUnauthorized());
        verifyNoInteractions(postService);
    }

    @Test
    void likeAndUnlikeReturnTheCurrentCount() throws Exception {
        when(postService.like(8L, 3L)).thenReturn(new LikeCountResponse(5));
        when(postService.unlike(8L, 3L)).thenReturn(new LikeCountResponse(4));

        mockMvc.perform(post(POSTS + "/3/likes").header(USER_ID_HEADER, "8"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.likeCount").value(5));
        mockMvc.perform(delete(POSTS + "/3/likes").header(USER_ID_HEADER, "8"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.likeCount").value(4));
    }

    @Test
    void likeRequiresTheUserHeader() throws Exception {
        mockMvc.perform(post(POSTS + "/3/likes")).andExpect(status().isUnauthorized());
        verifyNoInteractions(postService);
    }

    private static PostDetailResponse sampleDetail(boolean liked) {
        return new PostDetailResponse(
                3L,
                "오늘의 코디",
                "내용",
                PostCategory.DAILY,
                PostType.NORMAL,
                new AuthorResponse(7L, "fitzza"),
                null,
                4,
                liked,
                2,
                10,
                null,
                null);
    }
}
