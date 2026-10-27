package com.fitzza.product.worldcup.service;

import com.fitzza.product.global.dto.PageResponse;
import com.fitzza.product.global.exception.BusinessException;
import com.fitzza.product.global.exception.ErrorCode;
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
import java.util.Map;
import java.util.Set;
import java.util.function.Function;
import java.util.stream.Collectors;
import lombok.RequiredArgsConstructor;
import org.springframework.data.domain.PageRequest;
import org.springframework.data.domain.Sort;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
@RequiredArgsConstructor
@Transactional(readOnly = true)
public class WorldcupService {

    private static final Sort HISTORY_SORT = Sort.by(Sort.Direction.DESC, "completedAt", "worldcupHistoryId");

    private final WorldcupHistoryRepository worldcupHistoryRepository;
    private final ProductRepository productRepository;
    private final WishlistRepository wishlistRepository;
    private final ProductImageUrlService productImageUrlService;

    @Transactional
    public WorldcupResultResponse saveWorldcup(Long userId, WorldcupCreateRequest request) {
        Set<Long> candidateIds = Set.copyOf(request.candidateProductIds());
        validateCandidates(request, candidateIds);
        validateCandidatesAreWishlisted(userId, candidateIds);
        Map<Long, ProductEntity> productsById = productRepository.findAllWithBrandByProductIdIn(candidateIds).stream()
                .filter(product -> product.getStatus() != ProductStatus.HIDDEN)
                .collect(Collectors.toMap(ProductEntity::getProductId, Function.identity()));
        if (productsById.size() != candidateIds.size()) {
            throw new BusinessException(ErrorCode.PRODUCT_NOT_FOUND, "존재하지 않거나 노출되지 않는 후보 상품이 있습니다.");
        }
        WorldcupHistoryEntity history = worldcupHistoryRepository.save(WorldcupHistoryEntity.builder()
                .userId(userId)
                .winnerProduct(productsById.get(request.winnerProductId()))
                .build());
        return WorldcupResultResponse.from(history, productImageUrlService::resolve);
    }

    public WorldcupResultResponse findLatestWorldcup(Long userId) {
        return worldcupHistoryRepository.findFirstByUserIdOrderByCompletedAtDescWorldcupHistoryIdDesc(userId)
                .map(history -> WorldcupResultResponse.from(history, productImageUrlService::resolve))
                .orElseThrow(() -> new BusinessException(ErrorCode.WORLDCUP_NOT_FOUND));
    }

    public PageResponse<WorldcupResultResponse> findWorldcupHistories(Long userId, int page, int size) {
        return PageResponse.from(worldcupHistoryRepository
                .findAllByUserId(userId, PageRequest.of(page, size, HISTORY_SORT))
                .map(history -> WorldcupResultResponse.from(history, productImageUrlService::resolve)));
    }

    public WorldcupInternalResponse findWorldcup(Long worldcupHistoryId, Long userId) {
        WorldcupHistoryEntity history = worldcupHistoryRepository.findWithWinnerByWorldcupHistoryId(worldcupHistoryId)
                .orElseThrow(() -> new BusinessException(ErrorCode.WORLDCUP_NOT_FOUND));
        if (!history.getUserId().equals(userId)) {
            return WorldcupInternalResponse.notOwned(worldcupHistoryId);
        }
        return WorldcupInternalResponse.owned(history, productImageUrlService::resolve);
    }

    private void validateCandidates(WorldcupCreateRequest request, Set<Long> candidateIds) {
        if (candidateIds.size() != request.candidateProductIds().size()) {
            throw new BusinessException(ErrorCode.WORLDCUP_INVALID_CANDIDATES, "후보 상품 ID에 중복이 있습니다.");
        }
        if (!candidateIds.contains(request.winnerProductId())) {
            throw new BusinessException(ErrorCode.WORLDCUP_INVALID_CANDIDATES, "우승 상품은 후보에 포함되어야 합니다.");
        }
    }

    private void validateCandidatesAreWishlisted(Long userId, Set<Long> candidateIds) {
        List<String> itemIds = candidateIds.stream().map(String::valueOf).toList();
        if (wishlistRepository.countByUserIdAndItemIdIn(userId, itemIds) != candidateIds.size()) {
            throw new BusinessException(ErrorCode.WORLDCUP_INVALID_CANDIDATES, "월드컵 후보는 모두 찜한 상품이어야 합니다.");
        }
    }
}
