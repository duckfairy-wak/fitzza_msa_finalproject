package com.fitzza.product.wishlist.repository;

import com.fitzza.product.wishlist.entity.WishlistEntity;
import java.util.Collection;
import java.util.Optional;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.JpaRepository;

public interface WishlistRepository extends JpaRepository<WishlistEntity, Long> {

    Page<WishlistEntity> findByUserId(Long userId, Pageable pageable);

    Optional<WishlistEntity> findByUserIdAndItemId(Long userId, String itemId);

    boolean existsByUserIdAndItemId(Long userId, String itemId);

    long countByUserIdAndItemIdIn(Long userId, Collection<String> itemIds);

    long deleteByUserIdAndItemId(Long userId, String itemId);
}
