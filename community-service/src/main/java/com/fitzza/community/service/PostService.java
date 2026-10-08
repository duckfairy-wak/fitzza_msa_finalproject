package com.fitzza.community.service;

import com.fitzza.community.client.UserDirectory;
import com.fitzza.community.domain.Post;
import com.fitzza.community.domain.PostCategory;
import com.fitzza.community.domain.PostLikeId;
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
import com.fitzza.community.repository.CommentRepository;
import com.fitzza.community.repository.IdCount;
import com.fitzza.community.repository.PostLikeRepository;
import com.fitzza.community.repository.PostRepository;
import com.fitzza.community.repository.PostSpecifications;
import java.util.List;
import java.util.Map;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.PageRequest;
import org.springframework.data.domain.Pageable;
import org.springframework.data.domain.Sort;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class PostService {

    static final int MAX_PAGE_SIZE = 50;

    // 같은 시각에 쓰인 글의 순서가 페이지마다 바뀌지 않도록 ID를 보조 정렬로 둔다.
    private static final Sort NEWEST_FIRST = Sort.by(Sort.Order.desc("createdAt"), Sort.Order.desc("id"));

    private final PostRepository postRepository;
    private final PostLikeRepository postLikeRepository;
    private final CommentRepository commentRepository;
    private final UserDirectory userDirectory;

    public PostService(
            PostRepository postRepository,
            PostLikeRepository postLikeRepository,
            CommentRepository commentRepository,
            UserDirectory userDirectory) {
        this.postRepository = postRepository;
        this.postLikeRepository = postLikeRepository;
        this.commentRepository = commentRepository;
        this.userDirectory = userDirectory;
    }

    @Transactional(readOnly = true)
    public PostPageResponse getFeed(PostCategory category, PostType postType, String keyword, int page, int size) {
        Pageable pageable =
                PageRequest.of(Math.max(page, 0), Math.min(Math.max(size, 1), MAX_PAGE_SIZE), NEWEST_FIRST);
        Page<Post> posts = postRepository.findAll(PostSpecifications.feed(category, postType, keyword), pageable);
        if (posts.isEmpty()) {
            return new PostPageResponse(List.of(), posts.getNumber(), posts.getTotalPages());
        }

        List<Long> postIds = posts.getContent().stream().map(Post::getId).toList();
        Map<Long, Long> likeCounts = IdCount.toMap(postLikeRepository.countByPostIds(postIds));
        Map<Long, Long> commentCounts = IdCount.toMap(commentRepository.countActiveByPostIds(postIds));
        Map<Long, String> nicknames = userDirectory.findNicknames(
                posts.getContent().stream().map(Post::getUserId).toList());

        List<PostSummaryResponse> content = posts.getContent().stream()
                .map(post -> new PostSummaryResponse(
                        post.getId(),
                        post.getTitle(),
                        post.getCategory(),
                        post.getPostType(),
                        nicknames.get(post.getUserId()),
                        post.getCreatedAt(),
                        post.getImageUrl(),
                        likeCounts.getOrDefault(post.getId(), 0L),
                        commentCounts.getOrDefault(post.getId(), 0L)))
                .toList();
        return new PostPageResponse(content, posts.getNumber(), posts.getTotalPages());
    }

    // 상세를 열 때마다 조회수가 오른다. viewerId는 비로그인이면 null이다.
    @Transactional
    public PostDetailResponse getDetail(Long postId, Long viewerId) {
        if (postRepository.incrementViewCount(postId) == 0) {
            throw new CommunityApiException(ErrorCode.POST_NOT_FOUND);
        }
        Post post = findVisiblePost(postId);
        boolean liked = viewerId != null && postLikeRepository.existsById(new PostLikeId(postId, viewerId));
        String nickname = userDirectory.findNicknames(List.of(post.getUserId())).get(post.getUserId());
        return new PostDetailResponse(
                post.getId(),
                post.getTitle(),
                post.getContent(),
                post.getCategory(),
                post.getPostType(),
                new AuthorResponse(post.getUserId(), nickname),
                post.getImageUrl(),
                postLikeRepository.countByPostId(postId),
                liked,
                commentRepository.countByPostIdAndDeletedFalse(postId),
                post.getViewCount(),
                post.getCreatedAt(),
                post.getUpdatedAt());
    }

    @Transactional
    public PostCreatedResponse create(Long userId, PostCreateRequest request) {
        Post post = postRepository.save(Post.createNormal(
                userId, request.title(), request.content(), request.category(), request.imageUrl()));
        return new PostCreatedResponse(post.getId());
    }

    @Transactional
    public void update(Long userId, Long postId, PostUpdateRequest request) {
        Post post = findOwnPost(userId, postId);
        if (request.getTitle() != null) {
            post.changeTitle(request.getTitle());
        }
        if (request.getContent() != null) {
            post.changeContent(request.getContent());
        }
        if (request.getCategory() != null) {
            post.changeCategory(request.getCategory());
        }
        if (request.isImageUrlSent()) {
            post.changeImageUrl(request.getImageUrl());
        }
    }

    @Transactional
    public void delete(Long userId, Long postId) {
        findOwnPost(userId, postId).delete();
    }

    @Transactional
    public LikeCountResponse like(Long userId, Long postId) {
        requireVisiblePost(postId);
        postLikeRepository.insertIfAbsent(postId, userId);
        return new LikeCountResponse(postLikeRepository.countByPostId(postId));
    }

    @Transactional
    public LikeCountResponse unlike(Long userId, Long postId) {
        requireVisiblePost(postId);
        postLikeRepository.deleteLike(postId, userId);
        return new LikeCountResponse(postLikeRepository.countByPostId(postId));
    }

    private Post findOwnPost(Long userId, Long postId) {
        Post post = findVisiblePost(postId);
        if (!post.isWrittenBy(userId)) {
            throw new CommunityApiException(ErrorCode.NOT_AUTHOR);
        }
        return post;
    }

    private Post findVisiblePost(Long postId) {
        return postRepository
                .findByIdAndDeletedAtIsNull(postId)
                .orElseThrow(() -> new CommunityApiException(ErrorCode.POST_NOT_FOUND));
    }

    private void requireVisiblePost(Long postId) {
        if (!postRepository.existsByIdAndDeletedAtIsNull(postId)) {
            throw new CommunityApiException(ErrorCode.POST_NOT_FOUND);
        }
    }
}
