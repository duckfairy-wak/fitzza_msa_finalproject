package com.fitzza.product.worldcup.service;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.fitzza.product.global.exception.BusinessException;
import com.fitzza.product.global.exception.ErrorCode;
import com.fitzza.product.product.entity.BrandEntity;
import com.fitzza.product.product.entity.ProductEntity;
import com.fitzza.product.product.entity.ProductStatus;
import com.fitzza.product.product.repository.ProductRepository;
import com.fitzza.product.product.service.ProductImageUrlService;
import com.fitzza.product.wishlist.repository.WishlistRepository;
import com.fitzza.product.worldcup.dto.WorldcupCreateRequest;
import com.fitzza.product.worldcup.dto.WorldcupInternalResponse;
import com.fitzza.product.worldcup.dto.WorldcupResultResponse;
import com.fitzza.product.worldcup.entity.WorldcupHistoryEntity;
import com.fitzza.product.worldcup.repository.WorldcupHistoryRepository;
import java.util.List;
import java.util.Optional;
import org.assertj.core.api.ThrowableAssert.ThrowingCallable;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.test.util.ReflectionTestUtils;

@ExtendWith(MockitoExtension.class)
class WorldcupServiceTest {

    private static final Long USER_ID = 1L;

    @Mock
    private WorldcupHistoryRepository worldcupHistoryRepository;

    @Mock
    private ProductRepository productRepository;

    @Mock
    private WishlistRepository wishlistRepository;

    @Mock
    private ProductImageUrlService productImageUrlService;

    @InjectMocks
    private WorldcupService worldcupService;

    @BeforeEach
    void stubImageUrlPassthrough() {
        org.mockito.Mockito.lenient()
                .when(productImageUrlService.resolve(any()))
                .thenAnswer(invocation -> invocation.getArgument(0));
    }

    @Test
    void saveWorldcupStoresHistoryWithWinnerProduct() {
        ProductEntity winner = product(1L, ProductStatus.ON_SALE);
        ProductEntity loser = product(2L, ProductStatus.SOLD_OUT);
        when(wishlistRepository.countByUserIdAndItemIdIn(eq(USER_ID), any())).thenReturn(2L);
        when(productRepository.findAllWithBrandByProductIdIn(any())).thenReturn(List.of(winner, loser));
        when(worldcupHistoryRepository.save(any(WorldcupHistoryEntity.class))).thenAnswer(call -> {
            WorldcupHistoryEntity history = call.getArgument(0);
            ReflectionTestUtils.setField(history, "worldcupHistoryId", 10L);
            return history;
        });

        WorldcupResultResponse response =
                worldcupService.saveWorldcup(USER_ID, new WorldcupCreateRequest(1L, List.of(1L, 2L)));

        assertThat(response.worldcupHistoryId()).isEqualTo(10L);
        assertThat(response.winnerProduct().productId()).isEqualTo(1L);
    }

    @Test
    void saveWorldcupRejectsWinnerOutsideCandidates() {
        assertErrorCode(
                () -> worldcupService.saveWorldcup(USER_ID, new WorldcupCreateRequest(3L, List.of(1L, 2L))),
                ErrorCode.WORLDCUP_INVALID_CANDIDATES);
        verify(worldcupHistoryRepository, never()).save(any());
    }

    @Test
    void saveWorldcupRejectsDuplicateCandidates() {
        assertErrorCode(
                () -> worldcupService.saveWorldcup(USER_ID, new WorldcupCreateRequest(1L, List.of(1L, 1L, 2L))),
                ErrorCode.WORLDCUP_INVALID_CANDIDATES);
    }

    @Test
    void saveWorldcupRejectsCandidatesThatAreNotWishlisted() {
        when(wishlistRepository.countByUserIdAndItemIdIn(eq(USER_ID), any())).thenReturn(1L);

        assertErrorCode(
                () -> worldcupService.saveWorldcup(USER_ID, new WorldcupCreateRequest(1L, List.of(1L, 2L))),
                ErrorCode.WORLDCUP_INVALID_CANDIDATES);
        verify(worldcupHistoryRepository, never()).save(any());
        verify(productRepository, never()).findAllWithBrandByProductIdIn(any());
    }

    @Test
    void saveWorldcupRejectsMissingOrHiddenCandidates() {
        when(wishlistRepository.countByUserIdAndItemIdIn(eq(USER_ID), any())).thenReturn(2L);
        when(productRepository.findAllWithBrandByProductIdIn(any()))
                .thenReturn(List.of(product(1L, ProductStatus.ON_SALE), product(2L, ProductStatus.HIDDEN)));

        assertErrorCode(
                () -> worldcupService.saveWorldcup(USER_ID, new WorldcupCreateRequest(1L, List.of(1L, 2L))),
                ErrorCode.PRODUCT_NOT_FOUND);
        verify(worldcupHistoryRepository, never()).save(any());
    }

    @Test
    void findLatestWorldcupFailsWhenUserHasNoHistory() {
        when(worldcupHistoryRepository.findFirstByUserIdOrderByCompletedAtDescWorldcupHistoryIdDesc(USER_ID))
                .thenReturn(Optional.empty());

        assertErrorCode(() -> worldcupService.findLatestWorldcup(USER_ID), ErrorCode.WORLDCUP_NOT_FOUND);
    }

    @Test
    void findWorldcupReturnsProductOnlyForTheOwner() {
        WorldcupHistoryEntity history = WorldcupHistoryEntity.builder()
                .userId(USER_ID)
                .winnerProduct(product(1L, ProductStatus.ON_SALE))
                .build();
        ReflectionTestUtils.setField(history, "worldcupHistoryId", 10L);
        when(worldcupHistoryRepository.findWithWinnerByWorldcupHistoryId(10L)).thenReturn(Optional.of(history));

        WorldcupInternalResponse owned = worldcupService.findWorldcup(10L, USER_ID);
        WorldcupInternalResponse notOwned = worldcupService.findWorldcup(10L, 2L);

        assertThat(owned.owned()).isTrue();
        assertThat(owned.winnerProduct().productId()).isEqualTo(1L);
        assertThat(notOwned.owned()).isFalse();
        assertThat(notOwned.winnerProduct()).isNull();
        assertThat(notOwned.completedAt()).isNull();
    }

    @Test
    void findWorldcupFailsWhenHistoryDoesNotExist() {
        when(worldcupHistoryRepository.findWithWinnerByWorldcupHistoryId(99L)).thenReturn(Optional.empty());

        assertErrorCode(() -> worldcupService.findWorldcup(99L, USER_ID), ErrorCode.WORLDCUP_NOT_FOUND);
    }

    private ProductEntity product(Long productId, ProductStatus status) {
        return ProductEntity.builder()
                .productId(productId)
                .brand(BrandEntity.builder().brandName("Fitzza").build())
                .productName("상품 " + productId)
                .category1("TOP")
                .price(10000)
                .status(status)
                .build();
    }

    private void assertErrorCode(ThrowingCallable callable, ErrorCode expected) {
        assertThatThrownBy(callable)
                .isInstanceOf(BusinessException.class)
                .extracting(exception -> ((BusinessException) exception).getErrorCode())
                .isEqualTo(expected);
    }
}
