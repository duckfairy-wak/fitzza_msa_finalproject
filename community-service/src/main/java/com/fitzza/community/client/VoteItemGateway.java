package com.fitzza.community.client;

import com.fitzza.community.domain.VoteItemType;
import com.fitzza.community.domain.VoteOptionSource;

// 투표 선택지로 고른 상품·코디가 본인 것인지 확인하고 표시용 정보를 가져오는 자리.
public interface VoteItemGateway {

    VoteItemSnapshot resolve(
            Long userId, VoteOptionSource source, VoteItemType itemType, String itemId, String imageUrl);

    record VoteItemSnapshot(String imageUrl, String name, Integer price) {
    }
}
