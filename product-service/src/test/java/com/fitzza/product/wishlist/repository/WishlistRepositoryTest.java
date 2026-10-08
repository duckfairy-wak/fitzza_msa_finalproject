package com.fitzza.product.wishlist.repository;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import com.fitzza.product.product.entity.BrandEntity;
import com.fitzza.product.product.entity.ProductEntity;
import com.fitzza.product.product.entity.ProductStatus;
import com.fitzza.product.wishlist.entity.WishlistEntity;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.orm.jpa.DataJpaTest;
import org.springframework.boot.test.autoconfigure.orm.jpa.TestEntityManager;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.data.domain.PageRequest;

@DataJpaTest(properties = "spring.cloud.config.enabled=false")
class WishlistRepositoryTest {

    private static final Long USER_ID = 1L;
    private static final Long OTHER_USER_ID = 2L;

    @Autowired
    private TestEntityManager entityManager;

    @Autowired
    private WishlistRepository wishlistRepository;

    private ProductEntity topProduct;
    private ProductEntity bottomProduct;

    @BeforeEach
    void setUp() {
        BrandEntity brand = entityManager.persist(BrandEntity.builder().brandName("Fitzza").build());
        topProduct = persistProduct(brand, "TOP");
        bottomProduct = persistProduct(brand, "BOTTOM");
        persistWishlist(USER_ID, String.valueOf(topProduct.getProductId()));
        persistWishlist(USER_ID, String.valueOf(bottomProduct.getProductId()));
        persistWishlist(OTHER_USER_ID, String.valueOf(topProduct.getProductId()));
        entityManager.flush();
        entityManager.clear();
    }

    @Test
    void findByUserIdReturnsOnlyTheUsersWishlists() {
        var wishlists = wishlistRepository.findByUserId(USER_ID, PageRequest.of(0, 10));

        assertThat(wishlists.getTotalElements()).isEqualTo(2);
        assertThat(wishlists.getContent()).extracting(WishlistEntity::getItemId)
                .containsExactlyInAnyOrder(
                        String.valueOf(topProduct.getProductId()),
                        String.valueOf(bottomProduct.getProductId()));
    }

    @Test
    void saveRejectsDuplicateUserAndItem() {
        WishlistEntity duplicate = WishlistEntity.builder()
                .userId(USER_ID)
                .itemId(String.valueOf(topProduct.getProductId()))
                .build();

        assertThatThrownBy(() -> wishlistRepository.saveAndFlush(duplicate))
                .isInstanceOf(DataIntegrityViolationException.class);
    }

    @Test
    void deleteReturnsNumberOfDeletedRows() {
        String itemId = String.valueOf(topProduct.getProductId());
        long deleted = wishlistRepository.deleteByUserIdAndItemId(USER_ID, itemId);
        long deletedAgain = wishlistRepository.deleteByUserIdAndItemId(USER_ID, itemId);

        assertThat(deleted).isEqualTo(1);
        assertThat(deletedAgain).isZero();
    }

    @Test
    void existsChecksUserAndItem() {
        String itemId = String.valueOf(topProduct.getProductId());
        assertThat(wishlistRepository.existsByUserIdAndItemId(USER_ID, itemId)).isTrue();
        assertThat(wishlistRepository.existsByUserIdAndItemId(OTHER_USER_ID, itemId)).isTrue();
        assertThat(wishlistRepository.existsByUserIdAndItemId(OTHER_USER_ID, String.valueOf(bottomProduct.getProductId())))
                .isFalse();
    }

    private ProductEntity persistProduct(BrandEntity brand, String category1) {
        return entityManager.persist(ProductEntity.builder()
                .brand(brand)
                .productName(category1 + " 상품")
                .category1(category1)
                .price(10000)
                .status(ProductStatus.ON_SALE)
                .build());
    }

    private void persistWishlist(Long userId, String itemId) {
        entityManager.persist(WishlistEntity.builder().userId(userId).itemId(itemId).build());
    }
}
