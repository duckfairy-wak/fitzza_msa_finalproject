package com.fitzza.community.service;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

import com.fitzza.community.client.UserDirectory;
import com.fitzza.community.domain.Post;
import com.fitzza.community.domain.PostCategory;
import com.fitzza.community.domain.PostLikeId;
import com.fitzza.community.domain.PostType;
import com.fitzza.community.dto.LikeCountResponse;
import com.fitzza.community.dto.PostCreateRequest;
import com.fitzza.community.dto.PostCreatedResponse;
import com.fitzza.community.dto.PostDetailResponse;
import com.fitzza.community.dto.PostPageResponse;
import com.fitzza.community.dto.PostUpdateRequest;
import com.fitzza.community.exception.CommunityApiException;
import com.fitzza.community.exception.ErrorCode;
import com.fitzza.community.repository.CommentRepository;
import com.fitzza.community.repository.IdCount;
import com.fitzza.community.repository.PostLikeRepository;
import com.fitzza.community.repository.PostRepository;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.mockito.ArgumentMatchers;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.PageImpl;
import org.springframework.data.domain.PageRequest;
import org.springframework.data.domain.Pageable;
import org.springframework.data.domain.Sort;
import org.springframework.data.jpa.domain.Specification;
import org.springframework.test.util.ReflectionTestUtils;

class PostServiceTest {

    private static final Long AUTHOR_ID = 7L;
    private static final Long OTHER_ID = 8L;
    private static final Long POST_ID = 10L;
    private static final String IMAGE_URL = "https://cdn.example.com/posts/1.png";

    private final PostRepository postRepository = mock(PostRepository.class);
    private final PostLikeRepository postLikeRepository = mock(PostLikeRepository.class);
    private final CommentRepository commentRepository = mock(CommentRepository.class);
    private final UserDirectory userDirectory = mock(UserDirectory.class);
    private final PostService postService =
            new PostService(postRepository, postLikeRepository, commentRepository, userDirectory);

    @Test
    void createStoresTrimmedNormalPostForTheHeaderUser() {
        when(postRepository.save(any(Post.class))).thenAnswer(invocation -> {
            Post saved = invocation.getArgument(0);
            ReflectionTestUtils.setField(saved, "id", POST_ID);
            return saved;
        });

        PostCreatedResponse response = postService.create(
                AUTHOR_ID, new PostCreateRequest("  오늘의 코디  ", "  내용입니다  ", PostCategory.DAILY, "  "));

        assertThat(response.postId()).isEqualTo(POST_ID);
        ArgumentCaptor<Post> captor = ArgumentCaptor.forClass(Post.class);
        verify(postRepository).save(captor.capture());
        Post saved = captor.getValue();
        assertThat(saved.getUserId()).isEqualTo(AUTHOR_ID);
        assertThat(saved.getPostType()).isEqualTo(PostType.NORMAL);
        assertThat(saved.getTitle()).isEqualTo("오늘의 코디");
        assertThat(saved.getContent()).isEqualTo("내용입니다");
        assertThat(saved.getCategory()).isEqualTo(PostCategory.DAILY);
        assertThat(saved.getImageUrl()).isNull();
    }

    @Test
    void feedFillsCountsAndNicknamesForThePage() {
        Post newer = post(2L, AUTHOR_ID, IMAGE_URL);
        Post older = post(1L, OTHER_ID, null);
        when(postRepository.findAll(ArgumentMatchers.<Specification<Post>>any(), any(Pageable.class)))
                .thenReturn(new PageImpl<>(List.of(newer, older), PageRequest.of(0, 20), 2));
        when(postLikeRepository.countByPostIds(List.of(2L, 1L))).thenReturn(List.of(new IdCount(2L, 3L)));
        when(commentRepository.countActiveByPostIds(List.of(2L, 1L))).thenReturn(List.of(new IdCount(1L, 5L)));
        when(userDirectory.findNicknames(List.of(AUTHOR_ID, OTHER_ID))).thenReturn(Map.of(AUTHOR_ID, "fitzza"));

        PostPageResponse feed = postService.getFeed(PostCategory.FASHION, null, "코디", 0, 20);

        assertThat(feed.page()).isZero();
        assertThat(feed.totalPages()).isEqualTo(1);
        assertThat(feed.content()).hasSize(2);
        assertThat(feed.content().get(0).postId()).isEqualTo(2L);
        assertThat(feed.content().get(0).nickname()).isEqualTo("fitzza");
        assertThat(feed.content().get(0).thumbnailUrl()).isEqualTo(IMAGE_URL);
        assertThat(feed.content().get(0).likeCount()).isEqualTo(3);
        assertThat(feed.content().get(0).commentCount()).isZero();
        assertThat(feed.content().get(1).postId()).isEqualTo(1L);
        assertThat(feed.content().get(1).nickname()).isNull();
        assertThat(feed.content().get(1).likeCount()).isZero();
        assertThat(feed.content().get(1).commentCount()).isEqualTo(5);
    }

    @Test
    void feedClampsPagingAndSkipsLookupsWhenNothingMatches() {
        when(postRepository.findAll(ArgumentMatchers.<Specification<Post>>any(), any(Pageable.class)))
                .thenReturn(Page.<Post>empty());

        PostPageResponse feed = postService.getFeed(null, null, null, -3, 500);

        assertThat(feed.content()).isEmpty();
        ArgumentCaptor<Pageable> captor = ArgumentCaptor.forClass(Pageable.class);
        verify(postRepository).findAll(ArgumentMatchers.<Specification<Post>>any(), captor.capture());
        Pageable pageable = captor.getValue();
        assertThat(pageable.getPageNumber()).isZero();
        assertThat(pageable.getPageSize()).isEqualTo(PostService.MAX_PAGE_SIZE);
        assertThat(pageable.getSort())
                .isEqualTo(Sort.by(Sort.Order.desc("createdAt"), Sort.Order.desc("id")));
        verifyNoInteractions(postLikeRepository, commentRepository, userDirectory);
    }

    @Test
    void detailCountsTheViewAndTellsWhetherTheViewerLikedIt() {
        Post post = post(POST_ID, AUTHOR_ID, IMAGE_URL);
        when(postRepository.incrementViewCount(POST_ID)).thenReturn(1);
        when(postRepository.findByIdAndDeletedAtIsNull(POST_ID)).thenReturn(Optional.of(post));
        when(postLikeRepository.existsById(new PostLikeId(POST_ID, OTHER_ID))).thenReturn(true);
        when(postLikeRepository.countByPostId(POST_ID)).thenReturn(4L);
        when(commentRepository.countByPostIdAndDeletedFalse(POST_ID)).thenReturn(2L);
        when(userDirectory.findNicknames(List.of(AUTHOR_ID))).thenReturn(Map.of(AUTHOR_ID, "fitzza"));

        PostDetailResponse detail = postService.getDetail(POST_ID, OTHER_ID);

        verify(postRepository).incrementViewCount(POST_ID);
        assertThat(detail.postId()).isEqualTo(POST_ID);
        assertThat(detail.author().userId()).isEqualTo(AUTHOR_ID);
        assertThat(detail.author().nickname()).isEqualTo("fitzza");
        assertThat(detail.imageUrl()).isEqualTo(IMAGE_URL);
        assertThat(detail.liked()).isTrue();
        assertThat(detail.likeCount()).isEqualTo(4);
        assertThat(detail.commentCount()).isEqualTo(2);
    }

    @Test
    void detailForAnonymousViewerIsNeverLiked() {
        when(postRepository.incrementViewCount(POST_ID)).thenReturn(1);
        when(postRepository.findByIdAndDeletedAtIsNull(POST_ID))
                .thenReturn(Optional.of(post(POST_ID, AUTHOR_ID, null)));

        PostDetailResponse detail = postService.getDetail(POST_ID, null);

        assertThat(detail.liked()).isFalse();
        assertThat(detail.author().nickname()).isNull();
        verify(postLikeRepository, never()).existsById(any());
    }

    @Test
    void detailOfMissingOrDeletedPostIsNotFound() {
        when(postRepository.incrementViewCount(POST_ID)).thenReturn(0);

        assertThatThrownBy(() -> postService.getDetail(POST_ID, OTHER_ID))
                .isInstanceOf(CommunityApiException.class)
                .extracting("errorCode")
                .isEqualTo(ErrorCode.POST_NOT_FOUND);
        verify(postRepository, never()).findByIdAndDeletedAtIsNull(anyLong());
    }

    @Test
    void updateChangesOnlyTheFieldsThatWereSent() {
        Post post = post(POST_ID, AUTHOR_ID, IMAGE_URL);
        when(postRepository.findByIdAndDeletedAtIsNull(POST_ID)).thenReturn(Optional.of(post));
        PostUpdateRequest request = new PostUpdateRequest();
        request.setTitle("  새 제목  ");

        postService.update(AUTHOR_ID, POST_ID, request);

        assertThat(post.getTitle()).isEqualTo("새 제목");
        assertThat(post.getContent()).isEqualTo("내용");
        assertThat(post.getCategory()).isEqualTo(PostCategory.FASHION);
        assertThat(post.getImageUrl()).isEqualTo(IMAGE_URL);
    }

    @Test
    void updateRemovesTheImageWhenNullIsSent() {
        Post post = post(POST_ID, AUTHOR_ID, IMAGE_URL);
        when(postRepository.findByIdAndDeletedAtIsNull(POST_ID)).thenReturn(Optional.of(post));
        PostUpdateRequest request = new PostUpdateRequest();
        request.setImageUrl(null);
        request.setCategory(PostCategory.DAILY);

        postService.update(AUTHOR_ID, POST_ID, request);

        assertThat(post.getImageUrl()).isNull();
        assertThat(post.getCategory()).isEqualTo(PostCategory.DAILY);
        assertThat(post.getTitle()).isEqualTo("제목");
    }

    @Test
    void updateByAnotherUserIsRejected() {
        Post post = post(POST_ID, AUTHOR_ID, null);
        when(postRepository.findByIdAndDeletedAtIsNull(POST_ID)).thenReturn(Optional.of(post));
        PostUpdateRequest request = new PostUpdateRequest();
        request.setTitle("남의 글 고치기");

        assertThatThrownBy(() -> postService.update(OTHER_ID, POST_ID, request))
                .isInstanceOf(CommunityApiException.class)
                .extracting("errorCode")
                .isEqualTo(ErrorCode.NOT_AUTHOR);
        assertThat(post.getTitle()).isEqualTo("제목");
    }

    @Test
    void deleteKeepsTheRowAndMarksItDeleted() {
        Post post = post(POST_ID, AUTHOR_ID, null);
        when(postRepository.findByIdAndDeletedAtIsNull(POST_ID)).thenReturn(Optional.of(post));

        postService.delete(AUTHOR_ID, POST_ID);

        assertThat(post.isDeleted()).isTrue();
        verify(postRepository, never()).delete(any(Post.class));
    }

    @Test
    void deleteByAnotherUserIsRejected() {
        Post post = post(POST_ID, AUTHOR_ID, null);
        when(postRepository.findByIdAndDeletedAtIsNull(POST_ID)).thenReturn(Optional.of(post));

        assertThatThrownBy(() -> postService.delete(OTHER_ID, POST_ID))
                .isInstanceOf(CommunityApiException.class)
                .extracting("errorCode")
                .isEqualTo(ErrorCode.NOT_AUTHOR);
        assertThat(post.isDeleted()).isFalse();
    }

    @Test
    void likeInsertsOnceAndReturnsTheCurrentCount() {
        when(postRepository.existsByIdAndDeletedAtIsNull(POST_ID)).thenReturn(true);
        when(postLikeRepository.countByPostId(POST_ID)).thenReturn(1L);

        LikeCountResponse response = postService.like(OTHER_ID, POST_ID);

        verify(postLikeRepository).insertIfAbsent(POST_ID, OTHER_ID);
        assertThat(response.likeCount()).isEqualTo(1);
    }

    @Test
    void unlikeRemovesTheLikeAndReturnsTheCurrentCount() {
        when(postRepository.existsByIdAndDeletedAtIsNull(POST_ID)).thenReturn(true);
        when(postLikeRepository.countByPostId(POST_ID)).thenReturn(0L);

        LikeCountResponse response = postService.unlike(OTHER_ID, POST_ID);

        verify(postLikeRepository).deleteLike(POST_ID, OTHER_ID);
        assertThat(response.likeCount()).isZero();
    }

    @Test
    void likeOnMissingOrDeletedPostIsNotFound() {
        when(postRepository.existsByIdAndDeletedAtIsNull(POST_ID)).thenReturn(false);

        assertThatThrownBy(() -> postService.like(OTHER_ID, POST_ID))
                .isInstanceOf(CommunityApiException.class)
                .extracting("errorCode")
                .isEqualTo(ErrorCode.POST_NOT_FOUND);
        verify(postLikeRepository, never()).insertIfAbsent(anyLong(), anyLong());
    }

    private static Post post(Long postId, Long userId, String imageUrl) {
        Post post = Post.createNormal(userId, "제목", "내용", PostCategory.FASHION, imageUrl);
        ReflectionTestUtils.setField(post, "id", postId);
        return post;
    }
}
