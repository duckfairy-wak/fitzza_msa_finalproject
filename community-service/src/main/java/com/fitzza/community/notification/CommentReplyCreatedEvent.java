package com.fitzza.community.notification;

// 다른 사람이 내 댓글에 답글을 달았을 때 발행한다.
// 본인 댓글에 본인이 단 답글, 원댓글 작성자가 글 작성자인 경우(글 작성자는 CommentCreatedEvent로 이미 알림을 받음)는 알리지 않는다.
public record CommentReplyCreatedEvent(Long commentId, Long postId, Long parentAuthorId, String content) {
}
