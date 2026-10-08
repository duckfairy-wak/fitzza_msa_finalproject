package com.fitzza.community.service;

import com.fitzza.community.client.VoteItemGateway;
import com.fitzza.community.client.VoteItemGateway.VoteItemSnapshot;
import com.fitzza.community.domain.Post;
import com.fitzza.community.domain.Vote;
import com.fitzza.community.domain.VoteItemType;
import com.fitzza.community.domain.VoteOption;
import com.fitzza.community.domain.VoteOptionSource;
import com.fitzza.community.dto.VoteCastResponse;
import com.fitzza.community.dto.VoteClosedResponse;
import com.fitzza.community.dto.VoteOptionRequest;
import com.fitzza.community.dto.VoteOptionResult;
import com.fitzza.community.dto.VotePostCreateRequest;
import com.fitzza.community.dto.VotePostCreatedResponse;
import com.fitzza.community.dto.VoteResultResponse;
import com.fitzza.community.exception.CommunityApiException;
import com.fitzza.community.exception.ErrorCode;
import com.fitzza.community.repository.IdCount;
import com.fitzza.community.repository.PostRepository;
import com.fitzza.community.repository.VoteOptionRepository;
import com.fitzza.community.repository.VoteRepository;
import java.time.Instant;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.Set;
import java.util.UUID;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class VoteService {

    private final PostRepository postRepository;
    private final VoteOptionRepository voteOptionRepository;
    private final VoteRepository voteRepository;
    private final VoteItemGateway voteItemGateway;

    public VoteService(
            PostRepository postRepository,
            VoteOptionRepository voteOptionRepository,
            VoteRepository voteRepository,
            VoteItemGateway voteItemGateway) {
        this.postRepository = postRepository;
        this.voteOptionRepository = voteOptionRepository;
        this.voteRepository = voteRepository;
        this.voteItemGateway = voteItemGateway;
    }

    // 글과 선택지를 한 트랜잭션에 저장한다. 선택지 저장이 실패하면 글도 남지 않는다.
    @Transactional
    public VotePostCreatedResponse createVotePost(Long userId, VotePostCreateRequest request) {
        List<VoteOptionRequest> requested = request.options();
        requireConsistentOptions(requested);

        // 남의 추천·찜을 고른 요청은 글을 만들기 전에 걸러지도록 선택지부터 확인한다.
        List<VoteItemSnapshot> snapshots = new ArrayList<>();
        for (VoteOptionRequest option : requested) {
            snapshots.add(voteItemGateway.resolve(
                    userId, option.source(), option.itemType(), itemIdOf(option), option.imageUrl().trim()));
        }

        Post post = postRepository.save(
                Post.createVote(userId, request.title(), request.content(), request.category(), Instant.now()));
        List<VoteOption> options = new ArrayList<>();
        for (int index = 0; index < requested.size(); index++) {
            VoteOptionRequest option = requested.get(index);
            VoteItemSnapshot snapshot = snapshots.get(index);
            options.add(VoteOption.of(
                    post.getId(),
                    index + 1,
                    option.source(),
                    option.itemType(),
                    itemIdOf(option),
                    snapshot.imageUrl(),
                    snapshot.name(),
                    snapshot.price()));
        }
        voteOptionRepository.saveAll(options);
        return new VotePostCreatedResponse(post.getId(), post.getVoteEndAt());
    }

    @Transactional
    public VoteCastResponse vote(Long userId, Long postId, Long voteOptionId) {
        Post post = findVotePostForUpdate(postId);
        // 이미 투표했으면 다시 요청해도 처음 고른 선택지를 그대로 돌려준다(마감 뒤의 재요청 포함).
        Optional<Vote> existing = voteRepository.findByPostIdAndUserId(postId, userId);
        if (existing.isPresent()) {
            return new VoteCastResponse(existing.get().getVoteOptionId());
        }
        if (post.isVoteClosedAt(Instant.now())) {
            throw new CommunityApiException(ErrorCode.VOTE_CLOSED);
        }
        if (!voteOptionRepository.existsByIdAndPostId(voteOptionId, postId)) {
            throw new CommunityApiException(ErrorCode.INVALID_VOTE_OPTION);
        }
        voteRepository.insertIfAbsent(UUID.randomUUID().toString(), postId, userId, voteOptionId);
        return new VoteCastResponse(voteOptionId);
    }

    // viewerId는 비로그인이면 null이다.
    @Transactional(readOnly = true)
    public VoteResultResponse getResults(Long postId, Long viewerId) {
        Post post = postRepository
                .findByIdAndDeletedAtIsNull(postId)
                .orElseThrow(() -> new CommunityApiException(ErrorCode.POST_NOT_FOUND));
        requireVotePost(post);

        Map<Long, Long> counts = IdCount.toMap(voteRepository.countByOption(postId));
        long total = counts.values().stream().mapToLong(Long::longValue).sum();
        List<VoteOptionResult> results = voteOptionRepository.findByPostIdOrderByDisplayOrderAsc(postId).stream()
                .map(option -> {
                    long count = counts.getOrDefault(option.getId(), 0L);
                    double ratio = total == 0 ? 0.0 : (double) count / total;
                    return new VoteOptionResult(option.getId(), option.getLabel(), count, ratio);
                })
                .toList();
        Long myVoteOptionId = viewerId == null
                ? null
                : voteRepository
                        .findByPostIdAndUserId(postId, viewerId)
                        .map(Vote::getVoteOptionId)
                        .orElse(null);
        return new VoteResultResponse(
                results, total, post.getVoteEndAt(), post.isVoteClosedAt(Instant.now()), myVoteOptionId);
    }

    // 이미 끝난 투표를 다시 끝내도 결과는 같다.
    @Transactional
    public VoteClosedResponse close(Long userId, Long postId) {
        Post post = findVotePostForUpdate(postId);
        if (!post.isWrittenBy(userId)) {
            throw new CommunityApiException(ErrorCode.NOT_AUTHOR);
        }
        post.closeVote();
        return new VoteClosedResponse(true);
    }

    private Post findVotePostForUpdate(Long postId) {
        Post post = postRepository
                .findVisibleForUpdate(postId)
                .orElseThrow(() -> new CommunityApiException(ErrorCode.POST_NOT_FOUND));
        requireVotePost(post);
        return post;
    }

    private void requireVotePost(Post post) {
        if (!post.isVote()) {
            throw new CommunityApiException(ErrorCode.NOT_VOTE_POST);
        }
    }

    // 직접 올린 사진은 대상 ID가 없고, 상품·코디는 대상 ID가 있어야 한다. 같은 상품·코디를 두 번 넣을 수 없다.
    private void requireConsistentOptions(List<VoteOptionRequest> options) {
        if (options == null || options.size() < VoteOption.MIN_OPTIONS || options.size() > VoteOption.MAX_OPTIONS) {
            throw new CommunityApiException(ErrorCode.INVALID_VOTE_OPTIONS);
        }
        Set<String> seenItems = new HashSet<>();
        for (VoteOptionRequest option : options) {
            if (option == null
                    || option.source() == null
                    || option.itemType() == null
                    || option.imageUrl() == null
                    || option.imageUrl().isBlank()) {
                throw new CommunityApiException(ErrorCode.INVALID_VOTE_OPTIONS);
            }
            boolean uploaded = option.source() == VoteOptionSource.UPLOAD;
            boolean image = option.itemType() == VoteItemType.IMAGE;
            String itemId = itemIdOf(option);
            if (uploaded != image || (image && itemId != null) || (!image && itemId == null)) {
                throw new CommunityApiException(ErrorCode.INVALID_VOTE_OPTIONS);
            }
            if (!image && !seenItems.add(option.itemType() + ":" + itemId)) {
                throw new CommunityApiException(ErrorCode.INVALID_VOTE_OPTIONS);
            }
        }
    }

    private static String itemIdOf(VoteOptionRequest option) {
        String itemId = option.itemId();
        return itemId == null || itemId.isBlank() ? null : itemId.trim();
    }
}
