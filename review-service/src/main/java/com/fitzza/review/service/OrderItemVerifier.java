package com.fitzza.review.service;

import com.fitzza.review.client.OrderItems;
import com.fitzza.review.client.OrderItems.OrderItem;
import com.fitzza.review.exception.ErrorCode;
import com.fitzza.review.exception.ReviewApiException;
import java.util.Set;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;
import org.springframework.web.client.HttpServerErrorException;
import org.springframework.web.client.ResourceAccessException;

// 리뷰·설문은 내가 산(취소하지 않은) 주문 상품에만 쓸 수 있다. 주문 서비스가 응답하지 않으면 확인 없이 넘어가지 않고 503으로 거절한다.
// 401·400 같은 4xx는 토큰·요청 설정 문제이므로 그대로 던져 500과 오류 로그로 드러나게 한다.
@Component
public class OrderItemVerifier {

    // 결제·배송 단계가 없는 MVP라 주문하면 구매가 끝난 것으로 본다(2026-10-15 결정). 주문 상태
    // (PENDING·PAID·SHIPPING·COMPLETED·CANCELED) 중 취소된 주문만 막고, 상태가 비어 있으면 확인할 수 없어 막는다.
    static final Set<String> NON_REVIEWABLE_ORDER_STATUSES = Set.of("CANCELED");

    private static final Logger log = LoggerFactory.getLogger(OrderItemVerifier.class);

    private final OrderItems orderItems;

    public OrderItemVerifier(OrderItems orderItems) {
        this.orderItems = orderItems;
    }

    public OrderItem requireReviewable(Long userId, long orderItemId) {
        OrderItem orderItem;
        try {
            orderItem = orderItems.findOrderItem(orderItemId, userId)
                    .orElseThrow(() -> new ReviewApiException(ErrorCode.ORDER_ITEM_NOT_FOUND));
        } catch (ResourceAccessException | HttpServerErrorException exception) {
            log.warn("주문 서비스에서 주문 항목을 확인하지 못해 요청을 거부합니다: {}", exception.getMessage());
            throw new ReviewApiException(ErrorCode.ORDER_LOOKUP_UNAVAILABLE);
        }
        if (!orderItem.owned()) {
            throw new ReviewApiException(ErrorCode.NOT_ORDER_OWNER);
        }
        if (orderItem.orderStatus() == null || NON_REVIEWABLE_ORDER_STATUSES.contains(orderItem.orderStatus())) {
            throw new ReviewApiException(ErrorCode.ORDER_CANCELED);
        }
        return orderItem;
    }
}
