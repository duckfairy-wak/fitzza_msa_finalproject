package com.fitzza.community.notification;

import org.springframework.scheduling.annotation.Async;
import org.springframework.stereotype.Component;
import org.springframework.transaction.event.TransactionPhase;
import org.springframework.transaction.event.TransactionalEventListener;

@Component
public class CommentNotificationListener {

    static final String NOTIFICATION_TYPE = "COMMENT";
    static final String MESSAGE_PREFIX = "내 게시글에 새 댓글이 달렸어요: ";
    static final String REPLY_MESSAGE_PREFIX = "내 댓글에 답글이 달렸어요: ";
    static final int EXCERPT_LENGTH = 40;

    private final NotificationSender notificationSender;

    public CommentNotificationListener(NotificationSender notificationSender) {
        this.notificationSender = notificationSender;
    }

    // 댓글이 DB에 확정된 뒤에만 보내고, 응답을 기다리지 않도록 별도 스레드에서 보낸다.
    // eventId를 댓글 ID로 정해 두어 같은 댓글로 두 번 보내도 알림은 한 번만 생긴다.
    @Async
    @TransactionalEventListener(phase = TransactionPhase.AFTER_COMMIT)
    public void onCommentCreated(CommentCreatedEvent event) {
        notificationSender.send(new NotificationEvent(
                "comment-" + event.commentId(),
                NOTIFICATION_TYPE,
                event.postAuthorId(),
                String.valueOf(event.postId()),
                MESSAGE_PREFIX + excerpt(event.content())));
    }

    // 답글 알림은 글 작성자에게 가는 댓글 알림과 같은 답글로 함께 나갈 수 있어, eventId를 따로 둔다.
    @Async
    @TransactionalEventListener(phase = TransactionPhase.AFTER_COMMIT)
    public void onReplyCreated(CommentReplyCreatedEvent event) {
        notificationSender.send(new NotificationEvent(
                "comment-reply-" + event.commentId(),
                NOTIFICATION_TYPE,
                event.parentAuthorId(),
                String.valueOf(event.postId()),
                REPLY_MESSAGE_PREFIX + excerpt(event.content())));
    }

    static String excerpt(String content) {
        String singleLine = content.strip().replaceAll("\\s+", " ");
        if (singleLine.codePointCount(0, singleLine.length()) <= EXCERPT_LENGTH) {
            return singleLine;
        }
        int end = singleLine.offsetByCodePoints(0, EXCERPT_LENGTH);
        return singleLine.substring(0, end) + "…";
    }
}
