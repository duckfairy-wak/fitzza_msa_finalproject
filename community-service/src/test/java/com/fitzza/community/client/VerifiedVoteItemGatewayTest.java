package com.fitzza.community.client;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

import com.fitzza.community.client.ComboResults.ComboResult;
import com.fitzza.community.client.ProductCatalog.ProductSummary;
import com.fitzza.community.client.VoteItemGateway.VoteItemSnapshot;
import com.fitzza.community.domain.VoteItemType;
import com.fitzza.community.domain.VoteOption;
import com.fitzza.community.domain.VoteOptionSource;
import com.fitzza.community.exception.CommunityApiException;
import com.fitzza.community.exception.ErrorCode;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.Set;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.web.client.HttpClientErrorException;
import org.springframework.web.client.ResourceAccessException;

class VerifiedVoteItemGatewayTest {

    private static final Long USER_ID = 7L;
    private static final Long OTHER_USER_ID = 8L;
    private static final String REQUEST_IMAGE = "https://cdn.example.com/request.png";
    private static final String PRODUCT_IMAGE = "https://cdn.example.com/55.png";
    private static final String TOO_LONG_IMAGE =
            "https://cdn.example.com/55.png?sig=" + "a".repeat(VoteOption.IMAGE_URL_MAX_LENGTH);

    private final FakeProductCatalog catalog = new FakeProductCatalog();
    private final ComboResults combos = mock(ComboResults.class);
    private final VerifiedVoteItemGateway gateway = new VerifiedVoteItemGateway(catalog, combos);

    @Test
    void wishlistedProductIsStoredWithTheProductServiceImageNameAndPrice() {
        catalog.wishlist(USER_ID, 55L);
        catalog.product(new ProductSummary(55L, "Fitzza", "오버핏 셔츠", 39000, PRODUCT_IMAGE, "ON_SALE"));

        VoteItemSnapshot snapshot = resolveWishlist(USER_ID, 55L);

        assertThat(snapshot).isEqualTo(new VoteItemSnapshot(PRODUCT_IMAGE, "오버핏 셔츠", 39000));
    }

    @Test
    void soldOutProductCanStillBeAVoteOption() {
        catalog.wishlist(USER_ID, 55L);
        catalog.product(new ProductSummary(55L, "Fitzza", "오버핏 셔츠", 39000, PRODUCT_IMAGE, "SOLD_OUT"));

        assertThat(resolveWishlist(USER_ID, 55L).name()).isEqualTo("오버핏 셔츠");
    }

    @Test
    void productWithoutAnImageKeepsTheRequestImage() {
        catalog.wishlist(USER_ID, 55L);
        catalog.product(new ProductSummary(55L, "Fitzza", "오버핏 셔츠", 39000, null, "ON_SALE"));

        assertThat(resolveWishlist(USER_ID, 55L).imageUrl()).isEqualTo(REQUEST_IMAGE);
    }

    // 서비스 이미지가 저장 한도를 넘으면 저장 단계에서 실패하지 않도록 검증된 요청 이미지를 쓴다.
    @Test
    void aProductImageLongerThanTheColumnFallsBackToTheRequestImage() {
        catalog.wishlist(USER_ID, 55L);
        catalog.product(new ProductSummary(55L, "Fitzza", "오버핏 셔츠", 39000, TOO_LONG_IMAGE, "ON_SALE"));

        assertThat(resolveWishlist(USER_ID, 55L).imageUrl()).isEqualTo(REQUEST_IMAGE);
    }

    @Test
    void someoneElsesWishlistIsRejected() {
        catalog.wishlist(USER_ID, 55L);
        catalog.product(new ProductSummary(55L, "Fitzza", "오버핏 셔츠", 39000, PRODUCT_IMAGE, "ON_SALE"));

        assertRejectedWith(() -> resolveWishlist(OTHER_USER_ID, 55L), ErrorCode.NOT_WISHLISTED_ITEM);
    }

    @Test
    void hiddenOrMissingProductsAreRejected() {
        catalog.wishlist(USER_ID, 55L);
        catalog.wishlist(USER_ID, 56L);
        catalog.product(new ProductSummary(55L, "Fitzza", "숨긴 상품", 39000, PRODUCT_IMAGE, "HIDDEN"));

        assertRejectedWith(() -> resolveWishlist(USER_ID, 55L), ErrorCode.INVALID_VOTE_OPTIONS);
        assertRejectedWith(() -> resolveWishlist(USER_ID, 56L), ErrorCode.INVALID_VOTE_OPTIONS);
    }

    @Test
    void wishlistOptionsMustBeProductsWithAnId() {
        assertRejectedWith(
                () -> gateway.resolve(USER_ID, VoteOptionSource.WISHLIST, VoteItemType.COMBO, 55L, REQUEST_IMAGE),
                ErrorCode.INVALID_VOTE_OPTIONS);
        assertRejectedWith(() -> resolveWishlist(USER_ID, null), ErrorCode.INVALID_VOTE_OPTIONS);
        assertThat(catalog.calls).isZero();
    }

    @Test
    void voteIsRejectedInsteadOfTrustedWhenTheProductServiceIsDown() {
        catalog.down = true;

        assertRejectedWith(() -> resolveWishlist(USER_ID, 55L), ErrorCode.PRODUCT_LOOKUP_UNAVAILABLE);
    }

    // 서비스 토큰이 틀린 401 같은 설정 문제는 503(잠시 후 재시도)으로 감추지 않는다.
    @Test
    void aRejectedServiceTokenIsNotReportedAsATemporaryOutage() {
        catalog.failure = HttpClientErrorException.create(
                HttpStatus.UNAUTHORIZED, "unauthorized", HttpHeaders.EMPTY, null, null);

        assertThatThrownBy(() -> resolveWishlist(USER_ID, 55L)).isInstanceOf(HttpClientErrorException.class);
    }

    @Test
    void myRecommendedComboUsesItsFirstImageAndTotalPrice() {
        when(combos.findCombo(31L, USER_ID)).thenReturn(Optional.of(new ComboResult(
                true,
                List.of(new ResultProduct(1L, "셔츠", 39000, PRODUCT_IMAGE),
                        new ResultProduct(2L, "슬랙스", 50000, "https://cdn.example.com/2.png")),
                89000,
                "잘 어울려요")));

        assertThat(resolveRecommendedCombo(USER_ID, 31L))
                .isEqualTo(new VoteItemSnapshot(PRODUCT_IMAGE, null, 89000));
    }

    @Test
    void aComboWhoseFirstItemHasNoImageKeepsTheRequestImage() {
        when(combos.findCombo(31L, USER_ID)).thenReturn(Optional.of(new ComboResult(
                true, List.of(new ResultProduct(1L, "셔츠", 39000, null)), 39000, null)));

        assertThat(resolveRecommendedCombo(USER_ID, 31L).imageUrl()).isEqualTo(REQUEST_IMAGE);
    }

    @Test
    void aComboFirstImageLongerThanTheColumnFallsBackToTheRequestImage() {
        when(combos.findCombo(31L, USER_ID)).thenReturn(Optional.of(new ComboResult(
                true, List.of(new ResultProduct(1L, "셔츠", 39000, TOO_LONG_IMAGE)), 39000, null)));

        assertThat(resolveRecommendedCombo(USER_ID, 31L).imageUrl()).isEqualTo(REQUEST_IMAGE);
    }

    @Test
    void someoneElsesOrAMissingOrAnEmptyComboIsRejected() {
        when(combos.findCombo(31L, OTHER_USER_ID)).thenReturn(Optional.of(new ComboResult(false, null, null, null)));
        when(combos.findCombo(32L, USER_ID)).thenReturn(Optional.empty());
        when(combos.findCombo(33L, USER_ID)).thenReturn(Optional.of(new ComboResult(true, List.of(), 0, null)));

        assertRejectedWith(() -> resolveRecommendedCombo(OTHER_USER_ID, 31L), ErrorCode.NOT_RECOMMENDED_ITEM);
        assertRejectedWith(() -> resolveRecommendedCombo(USER_ID, 32L), ErrorCode.INVALID_VOTE_OPTIONS);
        assertRejectedWith(() -> resolveRecommendedCombo(USER_ID, 33L), ErrorCode.INVALID_VOTE_OPTIONS);
    }

    @Test
    void aRecommendedComboIsRejectedInsteadOfTrustedWhenTheRecommendationServiceIsDown() {
        when(combos.findCombo(31L, USER_ID)).thenThrow(new ResourceAccessException("not configured"));

        assertRejectedWith(() -> resolveRecommendedCombo(USER_ID, 31L), ErrorCode.RECOMMENDATION_LOOKUP_UNAVAILABLE);
    }

    // 받은 추천인지 확인할 API가 없어 단품은 상품이 있는지만 보고 상품 서비스 값으로 채운다.
    @Test
    void aRecommendedProductIsFilledFromTheProductServiceWithoutAWishlistCheck() {
        catalog.product(new ProductSummary(55L, "Fitzza", "오버핏 셔츠", 39000, PRODUCT_IMAGE, "ON_SALE"));

        VoteItemSnapshot snapshot =
                gateway.resolve(USER_ID, VoteOptionSource.AI_RECOMMEND, VoteItemType.PRODUCT, 55L, REQUEST_IMAGE);

        assertThat(snapshot).isEqualTo(new VoteItemSnapshot(PRODUCT_IMAGE, "오버핏 셔츠", 39000));
        verifyNoInteractions(combos);
    }

    @Test
    void aRecommendationNeedsAnId() {
        assertRejectedWith(
                () -> gateway.resolve(USER_ID, VoteOptionSource.AI_RECOMMEND, VoteItemType.COMBO, null, REQUEST_IMAGE),
                ErrorCode.INVALID_VOTE_OPTIONS);
        verifyNoInteractions(combos);
    }

    private VoteItemSnapshot resolveRecommendedCombo(Long userId, Long comboId) {
        return gateway.resolve(userId, VoteOptionSource.AI_RECOMMEND, VoteItemType.COMBO, comboId, REQUEST_IMAGE);
    }

    private VoteItemSnapshot resolveWishlist(Long userId, Long itemId) {
        return gateway.resolve(userId, VoteOptionSource.WISHLIST, VoteItemType.PRODUCT, itemId, REQUEST_IMAGE);
    }

    private static void assertRejectedWith(Runnable call, ErrorCode expected) {
        assertThatThrownBy(call::run)
                .isInstanceOfSatisfying(CommunityApiException.class,
                        exception -> assertThat(exception.getErrorCode()).isEqualTo(expected));
    }

    private static final class FakeProductCatalog implements ProductCatalog {

        private final Set<String> wishlists = new HashSet<>();
        private final Map<Long, ProductSummary> products = new HashMap<>();
        private boolean down;
        private RuntimeException failure;
        private int calls;

        void wishlist(Long userId, long productId) {
            wishlists.add(userId + ":" + productId);
        }

        void product(ProductSummary product) {
            products.put(product.productId(), product);
        }

        @Override
        public boolean isWishlisted(Long userId, long productId) {
            calls++;
            if (down) {
                throw new ResourceAccessException("product-service is down");
            }
            if (failure != null) {
                throw failure;
            }
            return wishlists.contains(userId + ":" + productId);
        }

        @Override
        public Optional<ProductSummary> findProduct(long productId) {
            calls++;
            if (down) {
                throw new ResourceAccessException("product-service is down");
            }
            return Optional.ofNullable(products.get(productId));
        }
    }
}
