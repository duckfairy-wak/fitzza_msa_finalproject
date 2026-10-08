package com.fitzza.product.wishlist.service;

import com.fitzza.product.global.dto.PageResponse;
import com.fitzza.product.global.exception.BusinessException;
import com.fitzza.product.global.exception.ErrorCode;
import com.fitzza.product.product.entity.ProductEntity;
import com.fitzza.product.product.entity.ProductStatus;
import com.fitzza.product.product.repository.ProductRepository;
import com.fitzza.product.wishlist.dto.WishlistCheckResponse;
import com.fitzza.product.wishlist.dto.WishlistCreateRequest;
import com.fitzza.product.wishlist.dto.WishlistItemResponse;
import com.fitzza.product.wishlist.dto.WishlistResponse;
import com.fitzza.product.wishlist.entity.WishlistEntity;
import com.fitzza.product.wishlist.repository.WishlistRepository;
import java.util.List;
import java.util.Map;
import java.util.function.Function;
import java.util.stream.Collectors;
import lombok.RequiredArgsConstructor;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.PageRequest;
import org.springframework.data.domain.Sort;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
@RequiredArgsConstructor
public class WishlistService {

    private static final Sort WISHLIST_SORT = Sort.by(Sort.Direction.DESC, "createdAt", "wishlistId");

    private final WishlistRepository wishlistRepository;
    private final ProductRepository productRepository;

    @Transactional(readOnly = true)
    public PageResponse<WishlistItemResponse> findWishlists(Long userId, int page, int size) {
        Page<WishlistEntity> wishlists = wishlistRepository.findByUserId(
                userId, PageRequest.of(page, size, WISHLIST_SORT));
        Map<String, ProductEntity> productsByItemId = loadWishlistProducts(wishlists.getContent());
        return PageResponse.from(wishlists.map(wishlist -> WishlistItemResponse.of(
                wishlist, productsByItemId.get(wishlist.getItemId()))));
    }

    public WishlistResponse addWishlist(Long userId, WishlistCreateRequest request) {
        String itemId = normalizeItemId(request.itemId());
        return wishlistRepository.findByUserIdAndItemId(userId, itemId)
                .map(WishlistResponse::from)
                .orElseGet(() -> createWishlist(userId, itemId));
    }

    @Transactional
    public void removeWishlist(Long userId, String itemId) {
        wishlistRepository.deleteByUserIdAndItemId(userId, normalizeItemId(itemId));
    }

    @Transactional(readOnly = true)
    public WishlistCheckResponse checkWishlist(Long userId, String itemId) {
        return new WishlistCheckResponse(wishlistRepository.existsByUserIdAndItemId(userId, normalizeItemId(itemId)));
    }

    private WishlistResponse createWishlist(Long userId, String itemId) {
        validateProductExists(Long.valueOf(itemId));
        try {
            WishlistEntity wishlist = wishlistRepository.saveAndFlush(WishlistEntity.builder()
                    .userId(userId)
                    .itemId(itemId)
                    .build());
            return WishlistResponse.from(wishlist);
        } catch (DataIntegrityViolationException exception) {
            return wishlistRepository.findByUserIdAndItemId(userId, itemId)
                    .map(WishlistResponse::from)
                    .orElseThrow(() -> exception);
        }
    }

    private String normalizeItemId(String itemId) {
        return String.valueOf(parseProductId(itemId.trim()));
    }

    private Long parseProductId(String itemId) {
        try {
            return Long.valueOf(itemId);
        } catch (NumberFormatException exception) {
            throw new BusinessException(ErrorCode.INVALID_REQUEST, "상품 itemId는 숫자여야 합니다.");
        }
    }

    private void validateProductExists(Long productId) {
        if (!productRepository.existsByProductIdAndStatusNot(productId, ProductStatus.HIDDEN)) {
            throw new BusinessException(ErrorCode.PRODUCT_NOT_FOUND);
        }
    }

    private Map<String, ProductEntity> loadWishlistProducts(List<WishlistEntity> wishlists) {
        List<Long> productIds = wishlists.stream()
                .map(wishlist -> Long.valueOf(wishlist.getItemId()))
                .toList();
        if (productIds.isEmpty()) {
            return Map.of();
        }
        return productRepository.findAllWithBrandByProductIdIn(productIds).stream()
                .collect(Collectors.toMap(product -> String.valueOf(product.getProductId()), Function.identity()));
    }
}
