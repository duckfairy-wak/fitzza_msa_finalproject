package com.fitzza.community.client;

import com.fitzza.community.client.ComboResults.ComboResult;
import com.fitzza.community.domain.VoteItemType;
import com.fitzza.community.domain.VoteOption;
import com.fitzza.community.domain.VoteOptionSource;
import com.fitzza.community.exception.CommunityApiException;
import com.fitzza.community.exception.ErrorCode;
import java.util.List;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;
import org.springframework.web.client.HttpServerErrorException;
import org.springframework.web.client.ResourceAccessException;

// 찜 출처는 상품 서비스에서 본인이 찜한 상품인지 확인하고, 이미지·상품명·가격을 상품 서비스 값으로 채운다.
// AI 추천 코디는 추천 서비스에서 본인이 받은 코디인지 확인하고, 첫 상품 이미지와 총 가격을 채운다.
// AI 추천 단품은 받은 추천인지 확인할 API가 없어 상품이 있는지만 확인하고 상품 서비스 값으로 채운다.
@Component
public class VerifiedVoteItemGateway implements VoteItemGateway {

    private static final Logger log = LoggerFactory.getLogger(VerifiedVoteItemGateway.class);
    private static final String HIDDEN_STATUS = "HIDDEN";

    private final ProductCatalog productCatalog;
    private final ComboResults comboResults;

    public VerifiedVoteItemGateway(ProductCatalog productCatalog, ComboResults comboResults) {
        this.productCatalog = productCatalog;
        this.comboResults = comboResults;
    }

    @Override
    public VoteItemSnapshot resolve(
            Long userId, VoteOptionSource source, VoteItemType itemType, Long itemId, String imageUrl) {
        return switch (source) {
            case WISHLIST -> resolveWishlisted(userId, itemType, itemId, imageUrl);
            case AI_RECOMMEND -> resolveRecommended(userId, itemType, itemId, imageUrl);
        };
    }

    private VoteItemSnapshot resolveWishlisted(Long userId, VoteItemType itemType, Long itemId, String imageUrl) {
        // 찜 목록에는 상품만 담긴다.
        if (itemType != VoteItemType.PRODUCT || itemId == null) {
            throw new CommunityApiException(ErrorCode.INVALID_VOTE_OPTIONS);
        }
        long productId = itemId;
        ProductCatalog.ProductSummary product;
        try {
            if (!productCatalog.isWishlisted(userId, productId)) {
                throw new CommunityApiException(ErrorCode.NOT_WISHLISTED_ITEM);
            }
            product = productCatalog.findProduct(productId).orElse(null);
        } catch (ResourceAccessException | HttpServerErrorException exception) {
            log.warn("상품 서비스에서 찜 상품을 확인하지 못해 투표 글 작성을 거부합니다: {}", exception.getMessage());
            throw new CommunityApiException(ErrorCode.PRODUCT_LOOKUP_UNAVAILABLE);
        }
        return productSnapshot(product, imageUrl);
    }

    private VoteItemSnapshot resolveRecommended(Long userId, VoteItemType itemType, Long itemId, String imageUrl) {
        if (itemId == null) {
            throw new CommunityApiException(ErrorCode.INVALID_VOTE_OPTIONS);
        }
        return switch (itemType) {
            case COMBO -> resolveRecommendedCombo(userId, itemId, imageUrl);
            case PRODUCT -> resolveRecommendedProduct(itemId, imageUrl);
        };
    }

    private VoteItemSnapshot resolveRecommendedCombo(Long userId, long comboId, String imageUrl) {
        ComboResult combo;
        try {
            combo = comboResults.findCombo(comboId, userId)
                    .orElseThrow(() -> new CommunityApiException(ErrorCode.INVALID_VOTE_OPTIONS));
        } catch (ResourceAccessException | HttpServerErrorException exception) {
            log.warn("추천 서비스에서 코디를 확인하지 못해 투표 글 작성을 거부합니다: {}", exception.getMessage());
            throw new CommunityApiException(ErrorCode.RECOMMENDATION_LOOKUP_UNAVAILABLE);
        }
        if (!combo.owned()) {
            throw new CommunityApiException(ErrorCode.NOT_RECOMMENDED_ITEM);
        }
        List<ResultProduct> items = combo.items() == null ? List.of() : combo.items();
        if (items.isEmpty()) {
            throw new CommunityApiException(ErrorCode.INVALID_VOTE_OPTIONS);
        }
        return new VoteItemSnapshot(storableImage(items.get(0).imageUrl(), imageUrl), null, combo.totalPrice());
    }

    private VoteItemSnapshot resolveRecommendedProduct(long productId, String imageUrl) {
        ProductCatalog.ProductSummary product;
        try {
            product = productCatalog.findProduct(productId).orElse(null);
        } catch (ResourceAccessException | HttpServerErrorException exception) {
            log.warn("상품 서비스에서 추천 상품을 확인하지 못해 투표 글 작성을 거부합니다: {}", exception.getMessage());
            throw new CommunityApiException(ErrorCode.PRODUCT_LOOKUP_UNAVAILABLE);
        }
        return productSnapshot(product, imageUrl);
    }

    private static VoteItemSnapshot productSnapshot(ProductCatalog.ProductSummary product, String imageUrl) {
        if (product == null || HIDDEN_STATUS.equals(product.status())) {
            throw new CommunityApiException(ErrorCode.INVALID_VOTE_OPTIONS);
        }
        return new VoteItemSnapshot(
                storableImage(product.imageUrl(), imageUrl), product.productName(), product.price());
    }

    // 서비스가 준 이미지를 우선 쓰되, 없거나 컬럼 길이를 넘으면 요청에 온 이미지를 쓴다.
    // 요청 이미지는 VoteOptionRequest에서 같은 길이 제한을 통과했고, Presigned URL은 자르면 서명이 깨진다.
    private static String storableImage(String serviceImage, String requestImage) {
        if (serviceImage == null
                || serviceImage.isBlank()
                || serviceImage.length() > VoteOption.IMAGE_URL_MAX_LENGTH) {
            return requestImage;
        }
        return serviceImage;
    }
}
