package com.fitzza.review.service;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

import com.fitzza.review.client.OrderItems.OrderItem;
import com.fitzza.review.domain.SizeFeedback;
import com.fitzza.review.domain.SizeSurvey;
import com.fitzza.review.dto.SurveyCreateRequest;
import com.fitzza.review.dto.SurveyResponse;
import com.fitzza.review.exception.ErrorCode;
import com.fitzza.review.exception.ReviewApiException;
import com.fitzza.review.repository.SizeSurveyRepository;
import java.util.Collections;
import java.util.List;
import java.util.stream.LongStream;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.test.util.ReflectionTestUtils;

class SurveyServiceTest {

    private static final Long USER_ID = 7L;
    private static final long ORDER_ITEM_ID = 500L;

    private final SizeSurveyRepository sizeSurveyRepository = mock(SizeSurveyRepository.class);
    private final OrderItemVerifier orderItemVerifier = mock(OrderItemVerifier.class);
    private final SurveyService surveyService = new SurveyService(sizeSurveyRepository, orderItemVerifier);

    @Test
    void createStoresTheOrderedOptionWithTheFeedback() {
        when(orderItemVerifier.requireReviewable(USER_ID, ORDER_ITEM_ID))
                .thenReturn(new OrderItem(true, 30L, 3L, "COMPLETED"));
        when(sizeSurveyRepository.saveAndFlush(any(SizeSurvey.class))).thenAnswer(invocation -> {
            SizeSurvey survey = invocation.getArgument(0);
            ReflectionTestUtils.setField(survey, "id", 21L);
            return survey;
        });

        Long surveyId = surveyService
                .create(USER_ID, new SurveyCreateRequest(ORDER_ITEM_ID, SizeFeedback.SMALL))
                .surveyId();

        ArgumentCaptor<SizeSurvey> saved = ArgumentCaptor.forClass(SizeSurvey.class);
        verify(sizeSurveyRepository).saveAndFlush(saved.capture());
        assertThat(surveyId).isEqualTo(21L);
        assertThat(saved.getValue().getOptionId()).isEqualTo(3L);
        assertThat(saved.getValue().getOrderItemId()).isEqualTo(ORDER_ITEM_ID);
        assertThat(saved.getValue().getSizeFeedback()).isEqualTo(SizeFeedback.SMALL);
    }

    @Test
    void createRejectsASecondSurveyBeforeAskingTheOrderService() {
        when(sizeSurveyRepository.existsByUserIdAndOrderItemId(USER_ID, ORDER_ITEM_ID)).thenReturn(true);

        assertThatThrownBy(() -> surveyService.create(USER_ID, new SurveyCreateRequest(ORDER_ITEM_ID, SizeFeedback.FIT)))
                .isInstanceOfSatisfying(ReviewApiException.class,
                        exception -> assertThat(exception.getErrorCode()).isEqualTo(ErrorCode.DUPLICATE_SURVEY));
        verifyNoInteractions(orderItemVerifier);
    }

    @Test
    void createPassesOnTheOrderCheckFailure() {
        when(orderItemVerifier.requireReviewable(USER_ID, ORDER_ITEM_ID))
                .thenThrow(new ReviewApiException(ErrorCode.ORDER_CANCELED));

        assertThatThrownBy(() -> surveyService.create(USER_ID, new SurveyCreateRequest(ORDER_ITEM_ID, SizeFeedback.BIG)))
                .isInstanceOfSatisfying(ReviewApiException.class,
                        exception -> assertThat(exception.getErrorCode()).isEqualTo(ErrorCode.ORDER_CANCELED));
        verify(sizeSurveyRepository, never()).saveAndFlush(any());
    }

    @Test
    void createTurnsAConcurrentDuplicateIntoDuplicateSurvey() {
        when(orderItemVerifier.requireReviewable(USER_ID, ORDER_ITEM_ID))
                .thenReturn(new OrderItem(true, 30L, 3L, "COMPLETED"));
        when(sizeSurveyRepository.saveAndFlush(any(SizeSurvey.class)))
                .thenThrow(new DataIntegrityViolationException("uk_size_surveys_user_order_item"));

        assertThatThrownBy(() -> surveyService.create(USER_ID, new SurveyCreateRequest(ORDER_ITEM_ID, SizeFeedback.FIT)))
                .isInstanceOfSatisfying(ReviewApiException.class,
                        exception -> assertThat(exception.getErrorCode()).isEqualTo(ErrorCode.DUPLICATE_SURVEY));
    }

    @Test
    void findMineReturnsOnlyTheSurveysTheRepositoryFound() {
        SizeSurvey survey = SizeSurvey.of(USER_ID, 3L, ORDER_ITEM_ID, SizeFeedback.FIT);
        ReflectionTestUtils.setField(survey, "id", 21L);
        when(sizeSurveyRepository.findByUserIdAndOrderItemIdInOrderByOrderItemIdAsc(USER_ID, List.of(500L, 501L)))
                .thenReturn(List.of(survey));

        assertThat(surveyService.findMine(USER_ID, List.of(500L, 501L)))
                .containsExactly(new SurveyResponse(21L, ORDER_ITEM_ID, SizeFeedback.FIT));
    }

    @Test
    void findMineNeedsOneToOneHundredIds() {
        List<Long> tooMany = LongStream.rangeClosed(1, 101).boxed().toList();

        assertThatThrownBy(() -> surveyService.findMine(USER_ID, Collections.emptyList()))
                .isInstanceOf(ReviewApiException.class);
        assertThatThrownBy(() -> surveyService.findMine(USER_ID, tooMany))
                .isInstanceOf(ReviewApiException.class);
        verifyNoInteractions(sizeSurveyRepository);
    }
}
