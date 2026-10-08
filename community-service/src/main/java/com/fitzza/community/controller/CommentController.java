package com.fitzza.community.controller;

import com.fitzza.community.dto.CommentCreateRequest;
import com.fitzza.community.dto.CommentCreatedResponse;
import com.fitzza.community.dto.CommentResponse;
import com.fitzza.community.dto.CommentUpdateRequest;
import com.fitzza.community.dto.LikeCountResponse;
import com.fitzza.community.security.AuthHeaders;
import com.fitzza.community.service.CommentService;
import jakarta.validation.Valid;
import java.util.List;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PatchMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.ResponseStatus;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/v1/community")
public class CommentController {

    private final CommentService commentService;

    public CommentController(CommentService commentService) {
        this.commentService = commentService;
    }

    @GetMapping("/posts/{postId}/comments")
    public List<CommentResponse> getComments(
            @PathVariable("postId") Long postId,
            @RequestHeader(name = AuthHeaders.USER_ID, required = false) Long userId) {
        return commentService.getComments(postId, userId);
    }

    @PostMapping("/posts/{postId}/comments")
    @ResponseStatus(HttpStatus.CREATED)
    public CommentCreatedResponse create(
            @RequestHeader(AuthHeaders.USER_ID) Long userId,
            @PathVariable("postId") Long postId,
            @Valid @RequestBody CommentCreateRequest request) {
        return commentService.create(userId, postId, request);
    }

    @PatchMapping("/comments/{commentId}")
    public void update(
            @RequestHeader(AuthHeaders.USER_ID) Long userId,
            @PathVariable("commentId") Long commentId,
            @Valid @RequestBody CommentUpdateRequest request) {
        commentService.update(userId, commentId, request);
    }

    @DeleteMapping("/comments/{commentId}")
    @ResponseStatus(HttpStatus.NO_CONTENT)
    public void delete(
            @RequestHeader(AuthHeaders.USER_ID) Long userId, @PathVariable("commentId") Long commentId) {
        commentService.delete(userId, commentId);
    }

    @PostMapping("/comments/{commentId}/likes")
    public LikeCountResponse like(
            @RequestHeader(AuthHeaders.USER_ID) Long userId, @PathVariable("commentId") Long commentId) {
        return commentService.like(userId, commentId);
    }

    @DeleteMapping("/comments/{commentId}/likes")
    public LikeCountResponse unlike(
            @RequestHeader(AuthHeaders.USER_ID) Long userId, @PathVariable("commentId") Long commentId) {
        return commentService.unlike(userId, commentId);
    }
}
