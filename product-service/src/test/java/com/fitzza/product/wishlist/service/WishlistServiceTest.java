package com.fitzza.product.wishlist.service;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.fitzza.product.global.exception.BusinessException;
import com.fitzza.product.global.exception.ErrorCode;
import com.fitzza.product.product.entity.ProductStatus;
import com.fitzza.product.product.repository.ProductRepository;
import com.fitzza.product.wishlist.dto.WishlistCreateRequest;
import com.fitzza.product.wishlist.dto.WishlistResponse;
import com.fitzza.product.wishlist.entity.WishlistEntity;
import com.fitzza.product.wishlist.repository.WishlistRepository;
import java.util.Optional;
import org.assertj.core.api.ThrowableAssert.ThrowingCallable;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.test.util.ReflectionTestUtils;

@ExtendWith(MockitoExtension.class)
class WishlistServiceTest {

    private static final Long USER_ID = 1L;

    @Mock
    private WishlistRepository wishlistRepository;

    @Mock
    private ProductRepository productRepository;

    @InjectMocks
    private WishlistService wishlistService;

    @Test
    void addWishlistNormalizesProductIdAndSaves() {
        when(wishlistRepository.findByUserIdAndItemId(USER_ID, "7")).thenReturn(Optional.empty());
        when(productRepository.existsByProductIdAndStatusNot(7L, ProductStatus.HIDDEN)).thenReturn(true);
        when(wishlistRepository.saveAndFlush(any(WishlistEntity.class))).thenAnswer(call -> {
            WishlistEntity wishlist = call.getArgument(0);
            ReflectionTestUtils.setField(wishlist, "wishlistId", 11L);
            return wishlist;
        });

        WishlistResponse response =
                wishlistService.addWishlist(USER_ID, new WishlistCreateRequest(" 007 "));

        ArgumentCaptor<WishlistEntity> captor = ArgumentCaptor.forClass(WishlistEntity.class);
        verify(wishlistRepository).saveAndFlush(captor.capture());
        assertThat(captor.getValue().getItemId()).isEqualTo("7");
        assertThat(captor.getValue().getUserId()).isEqualTo(USER_ID);
        assertThat(captor.getValue().getItemType()).isEqualTo("PRODUCT");
        assertThat(response.wishlistId()).isEqualTo(11L);
    }

    @Test
    void addWishlistReturnsExistingItemWithoutSavingAgain() {
        WishlistEntity existing = WishlistEntity.builder().userId(USER_ID).itemId("7").build();
        ReflectionTestUtils.setField(existing, "wishlistId", 5L);
        when(wishlistRepository.findByUserIdAndItemId(USER_ID, "7")).thenReturn(Optional.of(existing));

        WishlistResponse response = wishlistService.addWishlist(USER_ID, new WishlistCreateRequest("7"));

        assertThat(response.wishlistId()).isEqualTo(5L);
        verify(wishlistRepository, never()).saveAndFlush(any());
        verify(productRepository, never()).existsByProductIdAndStatusNot(any(), any());
    }

    @Test
    void addWishlistRejectsMissingOrHiddenProduct() {
        when(wishlistRepository.findByUserIdAndItemId(USER_ID, "7")).thenReturn(Optional.empty());
        when(productRepository.existsByProductIdAndStatusNot(7L, ProductStatus.HIDDEN)).thenReturn(false);

        assertErrorCode(
                () -> wishlistService.addWishlist(USER_ID, new WishlistCreateRequest("7")),
                ErrorCode.PRODUCT_NOT_FOUND);
    }

    @Test
    void addWishlistRejectsNonNumericProductId() {
        assertErrorCode(
                () -> wishlistService.addWishlist(USER_ID, new WishlistCreateRequest("abc")),
                ErrorCode.INVALID_REQUEST);
    }

    @Test
    void addWishlistReturnsExistingItemWhenConcurrentInsertConflicts() {
        WishlistEntity existing = WishlistEntity.builder().userId(USER_ID).itemId("7").build();
        ReflectionTestUtils.setField(existing, "wishlistId", 9L);
        when(wishlistRepository.findByUserIdAndItemId(USER_ID, "7"))
                .thenReturn(Optional.empty())
                .thenReturn(Optional.of(existing));
        when(productRepository.existsByProductIdAndStatusNot(7L, ProductStatus.HIDDEN)).thenReturn(true);
        when(wishlistRepository.saveAndFlush(any(WishlistEntity.class)))
                .thenThrow(new DataIntegrityViolationException("duplicate"));

        WishlistResponse response = wishlistService.addWishlist(USER_ID, new WishlistCreateRequest("7"));

        assertThat(response.wishlistId()).isEqualTo(9L);
    }

    @Test
    void removeWishlistDeletesWithoutFailingWhenNothingWasDeleted() {
        when(wishlistRepository.deleteByUserIdAndItemId(USER_ID, "7")).thenReturn(0L);

        wishlistService.removeWishlist(USER_ID, "7");

        verify(wishlistRepository).deleteByUserIdAndItemId(USER_ID, "7");
    }

    @Test
    void checkWishlistReturnsOwnershipOfTheItem() {
        when(wishlistRepository.existsByUserIdAndItemId(USER_ID, "7")).thenReturn(true);

        assertThat(wishlistService.checkWishlist(USER_ID, "7").wishlisted()).isTrue();
    }

    private void assertErrorCode(ThrowingCallable callable, ErrorCode expected) {
        assertThatThrownBy(callable)
                .isInstanceOf(BusinessException.class)
                .extracting(exception -> ((BusinessException) exception).getErrorCode())
                .isEqualTo(expected);
    }
}
