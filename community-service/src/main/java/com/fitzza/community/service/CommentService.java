package com.fitzza.community.service;

import com.fitzza.community.client.UserDirectory;
import com.fitzza.community.domain.Comment;
import com.fitzza.community.domain.CommentLikeId;
import com.fitzza.community.domain.Post;
import com.fitzza.community.dto.AuthorResponse;
import com.fitzza.community.dto.CommentCreateRequest;
import com.fitzza.community.dto.CommentCreatedResponse;
import com.fitzza.community.dto.CommentResponse;
import com.fitzza.community.dto.CommentUpdateRequest;
import com.fitzza.community.dto.LikeCountResponse;
import com.fitzza.community.dto.LikeStatusResponse;
import com.fitzza.community.exception.CommunityApiException;
import com.fitzza.community.exception.ErrorCode;
import com.fitzza.community.notification.CommentCreatedEvent;
import com.fitzza.community.notification.CommentReplyCreatedEvent;
import com.fitzza.community.repository.CommentLikeRepository;
import com.fitzza.community.repository.CommentRepository;
import com.fitzza.community.repository.IdCount;
import com.fitzza.community.repository.PostRepository;
import com.fitzza.community.votesupport.CommentSupportRequested;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import org.springframework.context.ApplicationEventPublisher;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class CommentService {

    static final String DELETED_CONTENT = "삭제된 댓글입니다";

    private final CommentRepository commentRepository;
    private final CommentLikeRepository commentLikeRepository;
    private final PostRepository postRepository;
    private final UserDirectory userDirectory;
    private final ApplicationEventPublisher eventPublisher;

    public CommentService(
            CommentRepository commentRepository,
            CommentLikeRepository commentLikeRepository,
            PostRepository postRepository,
            UserDirectory userDirectory,
            ApplicationEventPublisher eventPublisher) {
        this.commentRepository = commentRepository;
        this.commentLikeRepository = commentLikeRepository;
        this.postRepository = postRepository;
        this.userDirectory = userDirectory;
        this.eventPublisher = eventPublisher;
    }

    // 댓글은 작성순, 답글은 각 댓글 아래에 작성순으로 내려간다. viewerId는 비로그인이면 null이다.
    // supportedOptionId를 주면 그 선택지를 추천한다고 판정된 댓글·답글만 작성순으로 한 줄로 내려간다(replies는 빈 목록).
    @Transactional(readOnly = true)
    public List<CommentResponse> getComments(Long postId, Long viewerId, Long supportedOptionId) {
        requireVisiblePost(postId);
        List<Comment> comments = commentRepository.findByPostIdOrderByCreatedAtAscIdAsc(postId);
        List<Comment> active = comments.stream()
                .filter(comment -> !comment.isDeleted())
                .filter(comment -> supportedOptionId == null
                        || supportedOptionId.equals(comment.getSupportedOptionId()))
                .toList();
        if (active.isEmpty()) {
            return List.of();
        }

        List<Long> activeIds = active.stream().map(Comment::getId).toList();
        Map<Long, Long> likeCounts = IdCount.toMap(commentLikeRepository.countByCommentIds(activeIds));
        Set<Long> likedIds = viewerId == null
                ? Set.of()
                : new HashSet<>(commentLikeRepository.findLikedCommentIds(viewerId, activeIds));
        Map<Long, String> nicknames =
                userDirectory.findNicknames(active.stream().map(Comment::getUserId).toList());
        if (supportedOptionId != null) {
            return active.stream()
                    .map(comment -> toResponse(comment, List.of(), likeCounts, likedIds, nicknames))
                    .toList();
        }

        Map<Long, List<CommentResponse>> repliesByParent = new HashMap<>();
        for (Comment comment : active) {
            if (comment.isReply()) {
                repliesByParent
                        .computeIfAbsent(comment.getParentCommentId(), parentId -> new ArrayList<>())
                        .add(toResponse(comment, List.of(), likeCounts, likedIds, nicknames));
            }
        }

        List<CommentResponse> result = new ArrayList<>();
        for (Comment comment : comments) {
            if (comment.isReply()) {
                continue;
            }
            List<CommentResponse> replies = repliesByParent.getOrDefault(comment.getId(), List.of());
            if (!comment.isDeleted()) {
                result.add(toResponse(comment, replies, likeCounts, likedIds, nicknames));
            } else if (!replies.isEmpty()) {
                // 지워진 댓글이라도 답글이 남아 있으면 자리를 표시해 답글의 맥락을 유지한다.
                result.add(new CommentResponse(
                        comment.getId(), DELETED_CONTENT, null, 0, false, true, null, comment.getCreatedAt(), replies));
            }
        }
        return result;
    }

    // 다른 사람이 단 댓글·답글이면 글 작성자에게 알림을 보낸다. 실제 전송은 커밋 뒤에 한다.
    // 답글이면 원댓글 작성자에게도 알린다. 본인 댓글에 단 답글이거나, 원댓글 작성자가 글 작성자라 이미 알림을 받는 경우는 빼서 중복을 막는다.
    // 투표글이면 커밋 뒤 별도 스레드에서 이 댓글이 추천하는 선택지를 판정한다(실패해도 작성은 성공).
    @Transactional
    public CommentCreatedResponse create(Long userId, Long postId, CommentCreateRequest request) {
        Post post = postRepository
                .findByIdAndDeletedAtIsNull(postId)
                .orElseThrow(() -> new CommunityApiException(ErrorCode.POST_NOT_FOUND));
        Comment parent = request.parentCommentId() == null
                ? null
                : findReplyTarget(postId, request.parentCommentId());
        Comment comment = parent == null
                ? Comment.create(postId, userId, request.content())
                : Comment.replyTo(parent, userId, request.content());
        Comment saved = commentRepository.save(comment);
        if (post.isVote()) {
            eventPublisher.publishEvent(new CommentSupportRequested(saved.getId()));
        }
        if (!post.isWrittenBy(userId)) {
            eventPublisher.publishEvent(
                    new CommentCreatedEvent(saved.getId(), postId, post.getUserId(), saved.getContent()));
        }
        if (parent != null && !parent.isWrittenBy(userId) && !post.isWrittenBy(parent.getUserId())) {
            eventPublisher.publishEvent(
                    new CommentReplyCreatedEvent(saved.getId(), postId, parent.getUserId(), saved.getContent()));
        }
        return new CommentCreatedResponse(saved.getId());
    }

    // 내용이 바뀌면 지지 선택지를 지우고 커밋 뒤 다시 판정한다. 투표글이 아니면 판정 단계에서 건너뛴다.
    @Transactional
    public void update(Long userId, Long commentId, CommentUpdateRequest request) {
        findOwnComment(userId, commentId).changeContent(request.content());
        eventPublisher.publishEvent(new CommentSupportRequested(commentId));
    }

    @Transactional
    public void delete(Long userId, Long commentId) {
        findOwnComment(userId, commentId).delete();
    }

    @Transactional(readOnly = true)
    public LikeStatusResponse getLikeStatus(Long userId, Long commentId) {
        findActiveComment(commentId);
        return new LikeStatusResponse(
                commentLikeRepository.countByCommentId(commentId),
                commentLikeRepository.existsById(new CommentLikeId(commentId, userId)));
    }

    @Transactional
    public LikeCountResponse like(Long userId, Long commentId) {
        findActiveComment(commentId);
        commentLikeRepository.insertIfAbsent(commentId, userId);
        return new LikeCountResponse(commentLikeRepository.countByCommentId(commentId));
    }

    @Transactional
    public LikeCountResponse unlike(Long userId, Long commentId) {
        findActiveComment(commentId);
        commentLikeRepository.deleteLike(commentId, userId);
        return new LikeCountResponse(commentLikeRepository.countByCommentId(commentId));
    }

    // 답글은 같은 글의 최상위 댓글에만 달 수 있다(답글의 답글 불가).
    private Comment findReplyTarget(Long postId, Long parentCommentId) {
        Comment parent = findActiveComment(parentCommentId);
        if (!parent.getPostId().equals(postId) || parent.isReply()) {
            throw new CommunityApiException(ErrorCode.INVALID_PARENT_COMMENT);
        }
        return parent;
    }

    private Comment findOwnComment(Long userId, Long commentId) {
        Comment comment = findActiveComment(commentId);
        if (!comment.isWrittenBy(userId)) {
            throw new CommunityApiException(ErrorCode.NOT_AUTHOR);
        }
        return comment;
    }

    // 삭제된 글에 달린 댓글은 글과 함께 보이지 않으므로 없는 댓글로 다룬다.
    private Comment findActiveComment(Long commentId) {
        Comment comment = commentRepository
                .findById(commentId)
                .filter(found -> !found.isDeleted())
                .orElseThrow(() -> new CommunityApiException(ErrorCode.COMMENT_NOT_FOUND));
        if (!postRepository.existsByIdAndDeletedAtIsNull(comment.getPostId())) {
            throw new CommunityApiException(ErrorCode.COMMENT_NOT_FOUND);
        }
        return comment;
    }

    private void requireVisiblePost(Long postId) {
        if (!postRepository.existsByIdAndDeletedAtIsNull(postId)) {
            throw new CommunityApiException(ErrorCode.POST_NOT_FOUND);
        }
    }

    private CommentResponse toResponse(
            Comment comment,
            List<CommentResponse> replies,
            Map<Long, Long> likeCounts,
            Set<Long> likedIds,
            Map<Long, String> nicknames) {
        return new CommentResponse(
                comment.getId(),
                comment.getContent(),
                new AuthorResponse(comment.getUserId(), nicknames.get(comment.getUserId())),
                likeCounts.getOrDefault(comment.getId(), 0L),
                likedIds.contains(comment.getId()),
                false,
                comment.getSupportedOptionId(),
                comment.getCreatedAt(),
                replies);
    }
}
