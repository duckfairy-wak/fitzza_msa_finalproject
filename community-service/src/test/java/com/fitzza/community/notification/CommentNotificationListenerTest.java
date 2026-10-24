package com.fitzza.community.notification;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;

import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;

class CommentNotificationListenerTest {

    private final NotificationSender notificationSender = mock(NotificationSender.class);
    private final CommentNotificationListener listener = new CommentNotificationListener(notificationSender);

    @Test
    void sendsACommentNotificationToThePostAuthorKeyedByTheComment() {
        listener.onCommentCreated(new CommentCreatedEvent(100L, 10L, 7L, "잘 어울려요"));

        ArgumentCaptor<NotificationEvent> captor = ArgumentCaptor.forClass(NotificationEvent.class);
        verify(notificationSender).send(captor.capture());
        NotificationEvent event = captor.getValue();
        assertThat(event.eventId()).isEqualTo("comment-100");
        assertThat(event.type()).isEqualTo("COMMENT");
        assertThat(event.userId()).isEqualTo(7L);
        assertThat(event.targetId()).isEqualTo("10");
        assertThat(event.content()).isEqualTo("내 게시글에 새 댓글이 달렸어요: 잘 어울려요");
    }

    @Test
    void sendsAReplyNotificationToTheParentCommentAuthorWithItsOwnEventId() {
        listener.onReplyCreated(new CommentReplyCreatedEvent(101L, 10L, 8L, "저도 그렇게 생각해요"));

        ArgumentCaptor<NotificationEvent> captor = ArgumentCaptor.forClass(NotificationEvent.class);
        verify(notificationSender).send(captor.capture());
        NotificationEvent event = captor.getValue();
        assertThat(event.eventId()).isEqualTo("comment-reply-101");
        assertThat(event.type()).isEqualTo("COMMENT");
        assertThat(event.userId()).isEqualTo(8L);
        assertThat(event.targetId()).isEqualTo("10");
        assertThat(event.content()).isEqualTo("내 댓글에 답글이 달렸어요: 저도 그렇게 생각해요");
    }

    @Test
    void longCommentsAreCutToAShortSingleLineExcerpt() {
        String longComment = "가".repeat(30) + "\n\n" + "나".repeat(30);

        String excerpt = CommentNotificationListener.excerpt(longComment);

        assertThat(excerpt).isEqualTo("가".repeat(30) + " " + "나".repeat(9) + "…");
        assertThat(excerpt.codePointCount(0, excerpt.length()))
                .isEqualTo(CommentNotificationListener.EXCERPT_LENGTH + 1);
    }

    @Test
    void shortCommentsAreKeptWhole() {
        assertThat(CommentNotificationListener.excerpt("  예뻐요  ")).isEqualTo("예뻐요");
    }
}
