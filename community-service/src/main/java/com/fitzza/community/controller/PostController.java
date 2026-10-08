package com.fitzza.community.controller;

import com.fitzza.community.domain.PostCategory;
import com.fitzza.community.domain.PostType;
import com.fitzza.community.dto.LikeCountResponse;
import com.fitzza.community.dto.PostCreateRequest;
import com.fitzza.community.dto.PostCreatedResponse;
import com.fitzza.community.dto.PostDetailResponse;
import com.fitzza.community.dto.PostPageResponse;
import com.fitzza.community.dto.PostUpdateRequest;
import com.fitzza.community.security.AuthHeaders;
import com.fitzza.community.service.PostService;
import jakarta.validation.Valid;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PatchMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.ResponseStatus;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/v1/community/posts")
public class PostController {

    private final PostService postService;

    public PostController(PostService postService) {
        this.postService = postService;
    }

    @GetMapping
    public PostPageResponse getFeed(
            @RequestParam(name = "category", required = false) PostCategory category,
            @RequestParam(name = "postType", required = false) PostType postType,
            @RequestParam(name = "keyword", required = false) String keyword,
            @RequestParam(name = "page", defaultValue = "0") int page,
            @RequestParam(name = "size", defaultValue = "20") int size) {
        return postService.getFeed(category, postType, keyword, page, size);
    }

    @GetMapping("/{postId}")
    public PostDetailResponse getDetail(
            @PathVariable("postId") Long postId,
            @RequestHeader(name = AuthHeaders.USER_ID, required = false) Long userId) {
        return postService.getDetail(postId, userId);
    }

    @PostMapping
    @ResponseStatus(HttpStatus.CREATED)
    public PostCreatedResponse create(
            @RequestHeader(AuthHeaders.USER_ID) Long userId, @Valid @RequestBody PostCreateRequest request) {
        return postService.create(userId, request);
    }

    @PatchMapping("/{postId}")
    public void update(
            @RequestHeader(AuthHeaders.USER_ID) Long userId,
            @PathVariable("postId") Long postId,
            @Valid @RequestBody PostUpdateRequest request) {
        postService.update(userId, postId, request);
    }

    @DeleteMapping("/{postId}")
    @ResponseStatus(HttpStatus.NO_CONTENT)
    public void delete(@RequestHeader(AuthHeaders.USER_ID) Long userId, @PathVariable("postId") Long postId) {
        postService.delete(userId, postId);
    }

    @PostMapping("/{postId}/likes")
    public LikeCountResponse like(
            @RequestHeader(AuthHeaders.USER_ID) Long userId, @PathVariable("postId") Long postId) {
        return postService.like(userId, postId);
    }

    @DeleteMapping("/{postId}/likes")
    public LikeCountResponse unlike(
            @RequestHeader(AuthHeaders.USER_ID) Long userId, @PathVariable("postId") Long postId) {
        return postService.unlike(userId, postId);
    }
}
