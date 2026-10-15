package com.fitzza.review.service;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

import com.fitzza.review.client.OrderItems;
import com.fitzza.review.client.OrderItems.OrderItem;
import com.fitzza.review.exception.ErrorCode;
import com.fitzza.review.exception.ReviewApiException;
import java.util.Optional;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.web.client.HttpClientErrorException;
import org.springframework.web.client.HttpServerErrorException;
import org.springframework.web.client.ResourceAccessException;

class OrderItemVerifierTest {

    private final OrderItems orderItems = mock(OrderItems.class);
    private final OrderItemVerifier verifier = new OrderItemVerifier(orderItems);

    @Test
    void myCompletedOrderItemIsReviewable() {
        OrderItem item = new OrderItem(true, 55L, 501L, "COMPLETED");
        when(orderItems.findOrderItem(31L, 7L)).thenReturn(Optional.of(item));

        assertThat(verifier.requireReviewable(7L, 31L)).isEqualTo(item);
    }

    @Test
    void someoneElsesOrderMissingOrderAndUnfinishedOrderAreRejected() {
        when(orderItems.findOrderItem(31L, 8L)).thenReturn(Optional.of(new OrderItem(false, null, null, null)));
        assertRejected(8L, 31L, ErrorCode.NOT_ORDER_OWNER);

        when(orderItems.findOrderItem(404L, 7L)).thenReturn(Optional.empty());
        assertRejected(7L, 404L, ErrorCode.ORDER_ITEM_NOT_FOUND);

        when(orderItems.findOrderItem(32L, 7L)).thenReturn(Optional.of(new OrderItem(true, 55L, 501L, "CANCELED")));
        assertRejected(7L, 32L, ErrorCode.ORDER_CANCELED);

        when(orderItems.findOrderItem(34L, 7L)).thenReturn(Optional.of(new OrderItem(true, 55L, 501L, null)));
        assertRejected(7L, 34L, ErrorCode.ORDER_CANCELED);
    }

    // 결제·배송 단계가 없어 주문은 PENDING으로 남는다. 주문만 하면 리뷰·설문을 쓸 수 있어야 한다.
    @ParameterizedTest
    @ValueSource(strings = {"PENDING", "PAID", "SHIPPING", "COMPLETED"})
    void anyOrderThatIsNotCanceledCanBeReviewed(String status) {
        OrderItem item = new OrderItem(true, 55L, 501L, status);
        when(orderItems.findOrderItem(35L, 7L)).thenReturn(Optional.of(item));

        assertThat(verifier.requireReviewable(7L, 35L)).isEqualTo(item);
    }

    @Test
    void anUnreachableOrderServiceRefusesInsteadOfSkippingTheCheck() {
        when(orderItems.findOrderItem(31L, 7L)).thenThrow(new ResourceAccessException("connection refused"));
        assertRejected(7L, 31L, ErrorCode.ORDER_LOOKUP_UNAVAILABLE);

        when(orderItems.findOrderItem(33L, 7L)).thenThrow(
                HttpServerErrorException.create(HttpStatus.BAD_GATEWAY, "bad gateway", HttpHeaders.EMPTY, null, null));
        assertRejected(7L, 33L, ErrorCode.ORDER_LOOKUP_UNAVAILABLE);
    }

    // 서비스 토큰이 틀린 401 같은 설정 문제는 503(잠시 후 재시도)으로 감추지 않는다.
    @Test
    void aRejectedServiceTokenIsNotReportedAsATemporaryOutage() {
        when(orderItems.findOrderItem(31L, 7L)).thenThrow(
                HttpClientErrorException.create(HttpStatus.UNAUTHORIZED, "unauthorized", HttpHeaders.EMPTY, null, null));

        assertThatThrownBy(() -> verifier.requireReviewable(7L, 31L)).isInstanceOf(HttpClientErrorException.class);
    }

    private void assertRejected(Long userId, long orderItemId, ErrorCode expected) {
        assertThatThrownBy(() -> verifier.requireReviewable(userId, orderItemId))
                .isInstanceOfSatisfying(ReviewApiException.class,
                        exception -> assertThat(exception.getErrorCode()).isEqualTo(expected));
    }
}
