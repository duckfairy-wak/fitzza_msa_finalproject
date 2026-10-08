package com.fitzza.community.service;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.fitzza.community.client.UserDirectory;
import com.fitzza.community.domain.Comment;
import com.fitzza.community.dto.CommentCreateRequest;
import com.fitzza.community.dto.CommentCreatedResponse;
import com.fitzza.community.dto.CommentResponse;
import com.fitzza.community.dto.CommentUpdateRequest;
import com.fitzza.community.dto.LikeCountResponse;
import com.fitzza.community.exception.CommunityApiException;
import com.fitzza.community.exception.ErrorCode;
import com.fitzza.community.repository.CommentLikeRepository;
import com.fitzza.community.repository.CommentRepository;
import com.fitzza.community.repository.IdCount;
import com.fitzza.community.repository.PostRepository;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.test.util.ReflectionTestUtils;

class CommentServiceTest {

    private static final Long POST_ID = 10L;
    private static final Long OTHER_POST_ID = 11L;
    private static final Long AUTHOR_ID = 7L;
    private static final Long OTHER_ID = 8L;

    private final CommentRepository commentRepository = mock(CommentRepository.class);
    private final CommentLikeRepository commentLikeRepository = mock(CommentLikeRepository.class);
    private final PostRepository postRepository = mock(PostRepository.class);
    private final UserDirectory userDirectory = mock(UserDirectory.class);
    private final CommentService commentService =
            new CommentService(commentRepository, commentLikeRepository, postRepository, userDirectory);

    @BeforeEach
    void setUp() {
        when(postRepository.existsByIdAndDeletedAtIsNull(POST_ID)).thenReturn(true);
        when(postRepository.existsByIdAndDeletedAtIsNull(OTHER_POST_ID)).thenReturn(true);
        when(commentRepository.save(any(Comment.class))).thenAnswer(invocation -> {
            Comment saved = invocation.getArgument(0);
            ReflectionTestUtils.setField(saved, "id", 100L);
            return saved;
        });
    }

    @Test
    void createStoresTrimmedTopLevelComment() {
        CommentCreatedResponse response =
                commentService.create(AUTHOR_ID, POST_ID, new CommentCreateRequest("  잘 어울려요  ", null));

        assertThat(response.commentId()).isEqualTo(100L);
        Comment saved = savedComment();
        assertThat(saved.getPostId()).isEqualTo(POST_ID);
        assertThat(saved.getUserId()).isEqualTo(AUTHOR_ID);
        assertThat(saved.getContent()).isEqualTo("잘 어울려요");
        assertThat(saved.isReply()).isFalse();
    }

    @Test
    void createStoresReplyUnderTopLevelComment() {
        Comment parent = comment(1L, POST_ID, AUTHOR_ID, "원 댓글");
        when(commentRepository.findById(1L)).thenReturn(Optional.of(parent));

        commentService.create(OTHER_ID, POST_ID, new CommentCreateRequest("답글입니다", 1L));

        Comment saved = savedComment();
        assertThat(saved.getParentCommentId()).isEqualTo(1L);
        assertThat(saved.getPostId()).isEqualTo(POST_ID);
        assertThat(saved.getUserId()).isEqualTo(OTHER_ID);
    }

    @Test
    void replyToAReplyIsRejected() {
        Comment parent = comment(1L, POST_ID, AUTHOR_ID, "원 댓글");
        Comment reply = reply(2L, parent, OTHER_ID, "답글");
        when(commentRepository.findById(2L)).thenReturn(Optional.of(reply));

        assertThatThrownBy(() -> commentService.create(AUTHOR_ID, POST_ID, new CommentCreateRequest("답글의 답글", 2L)))
                .isInstanceOf(CommunityApiException.class)
                .extracting("errorCode")
                .isEqualTo(ErrorCode.INVALID_PARENT_COMMENT);
        verify(commentRepository, never()).save(any(Comment.class));
    }

    @Test
    void replyToACommentOfAnotherPostIsRejected() {
        Comment elsewhere = comment(3L, OTHER_POST_ID, AUTHOR_ID, "다른 글의 댓글");
        when(commentRepository.findById(3L)).thenReturn(Optional.of(elsewhere));

        assertThatThrownBy(() -> commentService.create(OTHER_ID, POST_ID, new CommentCreateRequest("답글", 3L)))
                .isInstanceOf(CommunityApiException.class)
                .extracting("errorCode")
                .isEqualTo(ErrorCode.INVALID_PARENT_COMMENT);
        verify(commentRepository, never()).save(any(Comment.class));
    }

    @Test
    void replyToADeletedCommentIsNotFound() {
        Comment parent = comment(1L, POST_ID, AUTHOR_ID, "원 댓글");
        parent.delete();
        when(commentRepository.findById(1L)).thenReturn(Optional.of(parent));

        assertThatThrownBy(() -> commentService.create(OTHER_ID, POST_ID, new CommentCreateRequest("답글", 1L)))
                .isInstanceOf(CommunityApiException.class)
                .extracting("errorCode")
                .isEqualTo(ErrorCode.COMMENT_NOT_FOUND);
    }

    @Test
    void commentOnMissingOrDeletedPostIsNotFound() {
        when(postRepository.existsByIdAndDeletedAtIsNull(POST_ID)).thenReturn(false);

        assertThatThrownBy(() -> commentService.create(AUTHOR_ID, POST_ID, new CommentCreateRequest("댓글", null)))
                .isInstanceOf(CommunityApiException.class)
                .extracting("errorCode")
                .isEqualTo(ErrorCode.POST_NOT_FOUND);
        verify(commentRepository, never()).save(any(Comment.class));
    }

    @Test
    void listNestsRepliesAndFillsLikesAndNicknames() {
        Comment first = comment(1L, POST_ID, AUTHOR_ID, "첫 댓글");
        Comment second = comment(2L, POST_ID, OTHER_ID, "둘째 댓글");
        Comment replyToFirst = reply(3L, first, OTHER_ID, "첫 댓글의 답글");
        when(commentRepository.findByPostIdOrderByCreatedAtAscIdAsc(POST_ID))
                .thenReturn(List.of(first, second, replyToFirst));
        when(commentLikeRepository.countByCommentIds(List.of(1L, 2L, 3L)))
                .thenReturn(List.of(new IdCount(1L, 2L)));
        when(commentLikeRepository.findLikedCommentIds(OTHER_ID, List.of(1L, 2L, 3L))).thenReturn(List.of(1L));
        when(userDirectory.findNicknames(List.of(AUTHOR_ID, OTHER_ID, OTHER_ID)))
                .thenReturn(Map.of(AUTHOR_ID, "fitzza", OTHER_ID, "coordi"));

        List<CommentResponse> comments = commentService.getComments(POST_ID, OTHER_ID);

        assertThat(comments).extracting(CommentResponse::commentId).containsExactly(1L, 2L);
        CommentResponse top = comments.get(0);
        assertThat(top.content()).isEqualTo("첫 댓글");
        assertThat(top.author().nickname()).isEqualTo("fitzza");
        assertThat(top.likeCount()).isEqualTo(2);
        assertThat(top.liked()).isTrue();
        assertThat(top.deleted()).isFalse();
        assertThat(top.replies()).extracting(CommentResponse::commentId).containsExactly(3L);
        assertThat(top.replies().get(0).author().nickname()).isEqualTo("coordi");
        assertThat(top.replies().get(0).liked()).isFalse();
        assertThat(comments.get(1).replies()).isEmpty();
    }

    @Test
    void listShowsDeletedCommentOnlyWhileItStillHasReplies() {
        Comment deletedWithReply = comment(1L, POST_ID, AUTHOR_ID, "지워진 댓글");
        deletedWithReply.delete();
        Comment deletedAlone = comment(2L, POST_ID, AUTHOR_ID, "혼자 지워진 댓글");
        deletedAlone.delete();
        Comment reply = reply(3L, deletedWithReply, OTHER_ID, "남은 답글");
        Comment deletedReply = reply(4L, deletedWithReply, OTHER_ID, "지워진 답글");
        deletedReply.delete();
        when(commentRepository.findByPostIdOrderByCreatedAtAscIdAsc(POST_ID))
                .thenReturn(List.of(deletedWithReply, deletedAlone, reply, deletedReply));
        when(commentLikeRepository.countByCommentIds(List.of(3L))).thenReturn(List.of());
        when(userDirectory.findNicknames(List.of(OTHER_ID))).thenReturn(Map.of(OTHER_ID, "coordi"));

        List<CommentResponse> comments = commentService.getComments(POST_ID, null);

        assertThat(comments).hasSize(1);
        CommentResponse placeholder = comments.get(0);
        assertThat(placeholder.commentId()).isEqualTo(1L);
        assertThat(placeholder.deleted()).isTrue();
        assertThat(placeholder.content()).isEqualTo(CommentService.DELETED_CONTENT);
        assertThat(placeholder.author()).isNull();
        assertThat(placeholder.replies()).extracting(CommentResponse::commentId).containsExactly(3L);
        verify(commentLikeRepository, never()).findLikedCommentIds(anyLong(), any());
    }

    @Test
    void listOfMissingOrDeletedPostIsNotFound() {
        when(postRepository.existsByIdAndDeletedAtIsNull(POST_ID)).thenReturn(false);

        assertThatThrownBy(() -> commentService.getComments(POST_ID, null))
                .isInstanceOf(CommunityApiException.class)
                .extracting("errorCode")
                .isEqualTo(ErrorCode.POST_NOT_FOUND);
    }

    @Test
    void updateChangesContentForTheAuthor() {
        Comment comment = comment(1L, POST_ID, AUTHOR_ID, "원래 내용");
        when(commentRepository.findById(1L)).thenReturn(Optional.of(comment));

        commentService.update(AUTHOR_ID, 1L, new CommentUpdateRequest("  고친 내용  "));

        assertThat(comment.getContent()).isEqualTo("고친 내용");
    }

    @Test
    void updateByAnotherUserIsRejected() {
        Comment comment = comment(1L, POST_ID, AUTHOR_ID, "원래 내용");
        when(commentRepository.findById(1L)).thenReturn(Optional.of(comment));

        assertThatThrownBy(() -> commentService.update(OTHER_ID, 1L, new CommentUpdateRequest("남의 댓글")))
                .isInstanceOf(CommunityApiException.class)
                .extracting("errorCode")
                .isEqualTo(ErrorCode.NOT_AUTHOR);
        assertThat(comment.getContent()).isEqualTo("원래 내용");
    }

    @Test
    void deleteKeepsTheRowAndMarksItDeleted() {
        Comment comment = comment(1L, POST_ID, AUTHOR_ID, "지울 댓글");
        when(commentRepository.findById(1L)).thenReturn(Optional.of(comment));

        commentService.delete(AUTHOR_ID, 1L);

        assertThat(comment.isDeleted()).isTrue();
        verify(commentRepository, never()).delete(any(Comment.class));
    }

    @Test
    void deletingAnAlreadyDeletedCommentIsNotFound() {
        Comment comment = comment(1L, POST_ID, AUTHOR_ID, "지운 댓글");
        comment.delete();
        when(commentRepository.findById(1L)).thenReturn(Optional.of(comment));

        assertThatThrownBy(() -> commentService.delete(AUTHOR_ID, 1L))
                .isInstanceOf(CommunityApiException.class)
                .extracting("errorCode")
                .isEqualTo(ErrorCode.COMMENT_NOT_FOUND);
    }

    @Test
    void likeInsertsOnceAndReturnsTheCurrentCount() {
        when(commentRepository.findById(1L)).thenReturn(Optional.of(comment(1L, POST_ID, AUTHOR_ID, "댓글")));
        when(commentLikeRepository.countByCommentId(1L)).thenReturn(1L);

        LikeCountResponse response = commentService.like(OTHER_ID, 1L);

        verify(commentLikeRepository).insertIfAbsent(1L, OTHER_ID);
        assertThat(response.likeCount()).isEqualTo(1);
    }

    @Test
    void unlikeRemovesTheLikeAndReturnsTheCurrentCount() {
        when(commentRepository.findById(1L)).thenReturn(Optional.of(comment(1L, POST_ID, AUTHOR_ID, "댓글")));
        when(commentLikeRepository.countByCommentId(1L)).thenReturn(0L);

        LikeCountResponse response = commentService.unlike(OTHER_ID, 1L);

        verify(commentLikeRepository).deleteLike(1L, OTHER_ID);
        assertThat(response.likeCount()).isZero();
    }

    @Test
    void likeOnACommentOfADeletedPostIsNotFound() {
        when(commentRepository.findById(1L)).thenReturn(Optional.of(comment(1L, POST_ID, AUTHOR_ID, "댓글")));
        when(postRepository.existsByIdAndDeletedAtIsNull(POST_ID)).thenReturn(false);

        assertThatThrownBy(() -> commentService.like(OTHER_ID, 1L))
                .isInstanceOf(CommunityApiException.class)
                .extracting("errorCode")
                .isEqualTo(ErrorCode.COMMENT_NOT_FOUND);
        verify(commentLikeRepository, never()).insertIfAbsent(anyLong(), anyLong());
    }

    private Comment savedComment() {
        ArgumentCaptor<Comment> captor = ArgumentCaptor.forClass(Comment.class);
        verify(commentRepository).save(captor.capture());
        return captor.getValue();
    }

    private static Comment comment(Long commentId, Long postId, Long userId, String content) {
        Comment comment = Comment.create(postId, userId, content);
        ReflectionTestUtils.setField(comment, "id", commentId);
        return comment;
    }

    private static Comment reply(Long commentId, Comment parent, Long userId, String content) {
        Comment reply = Comment.replyTo(parent, userId, content);
        ReflectionTestUtils.setField(reply, "id", commentId);
        return reply;
    }
}
