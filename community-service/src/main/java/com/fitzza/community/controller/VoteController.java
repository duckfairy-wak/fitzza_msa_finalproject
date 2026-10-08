package com.fitzza.community.controller;

import com.fitzza.community.dto.VoteCastResponse;
import com.fitzza.community.dto.VoteClosedResponse;
import com.fitzza.community.dto.VotePostCreateRequest;
import com.fitzza.community.dto.VotePostCreatedResponse;
import com.fitzza.community.dto.VoteRequest;
import com.fitzza.community.dto.VoteResultResponse;
import com.fitzza.community.security.AuthHeaders;
import com.fitzza.community.service.VoteService;
import jakarta.validation.Valid;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.ResponseStatus;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/v1/community/posts")
public class VoteController {

    private final VoteService voteService;

    public VoteController(VoteService voteService) {
        this.voteService = voteService;
    }

    @PostMapping("/vote")
    @ResponseStatus(HttpStatus.CREATED)
    public VotePostCreatedResponse createVotePost(
            @RequestHeader(AuthHeaders.USER_ID) Long userId, @Valid @RequestBody VotePostCreateRequest request) {
        return voteService.createVotePost(userId, request);
    }

    @PostMapping("/{postId}/votes")
    public VoteCastResponse vote(
            @RequestHeader(AuthHeaders.USER_ID) Long userId,
            @PathVariable("postId") Long postId,
            @Valid @RequestBody VoteRequest request) {
        return voteService.vote(userId, postId, request.voteOptionId());
    }

    @GetMapping("/{postId}/votes")
    public VoteResultResponse getResults(
            @PathVariable("postId") Long postId,
            @RequestHeader(name = AuthHeaders.USER_ID, required = false) Long userId) {
        return voteService.getResults(postId, userId);
    }

    @PostMapping("/{postId}/votes/close")
    public VoteClosedResponse close(
            @RequestHeader(AuthHeaders.USER_ID) Long userId, @PathVariable("postId") Long postId) {
        return voteService.close(userId, postId);
    }
}
