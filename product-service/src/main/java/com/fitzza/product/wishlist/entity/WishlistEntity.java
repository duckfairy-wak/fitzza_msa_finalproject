package com.fitzza.product.wishlist.entity;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import jakarta.persistence.UniqueConstraint;
import java.time.LocalDateTime;
import lombok.AccessLevel;
import lombok.Builder;
import lombok.Getter;
import lombok.NoArgsConstructor;
import org.hibernate.annotations.CreationTimestamp;

@Entity
@Table(name = "wishlist", uniqueConstraints = @UniqueConstraint(
        name = "uk_wishlist_user_item",
        columnNames = {"user_id", "item_id", "item_type"}))
@Getter
@NoArgsConstructor(access = AccessLevel.PROTECTED)
public class WishlistEntity {

    private static final String PRODUCT_ITEM_TYPE = "PRODUCT";

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    @Column(name = "wishlist_id")
    private Long wishlistId;

    @Column(name = "user_id", nullable = false)
    private Long userId;

    @Column(name = "item_id", nullable = false, length = 100)
    private String itemId;

    @Column(name = "item_type", nullable = false, length = 20)
    private String itemType;

    @CreationTimestamp
    @Column(name = "created_at", nullable = false, updatable = false)
    private LocalDateTime createdAt;

    @Builder
    private WishlistEntity(Long userId, String itemId) {
        this.userId = userId;
        this.itemId = itemId;
        this.itemType = PRODUCT_ITEM_TYPE;
    }
}
