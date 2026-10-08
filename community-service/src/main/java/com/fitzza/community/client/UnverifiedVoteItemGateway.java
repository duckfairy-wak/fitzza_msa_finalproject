package com.fitzza.community.client;

import com.fitzza.community.domain.VoteItemType;
import com.fitzza.community.domain.VoteOptionSource;
import org.springframework.stereotype.Component;

// 추천·피팅 서비스와 찜 서비스의 내부 API가 아직 없어서, 소유 확인 없이 요청에 온 이미지 주소만 쓴다.
// 두 API가 생기면 본인 것이 아닐 때 거부하고 상품명·가격을 채우는 구현으로 바꾼다.
@Component
public class UnverifiedVoteItemGateway implements VoteItemGateway {

    @Override
    public VoteItemSnapshot resolve(
            Long userId, VoteOptionSource source, VoteItemType itemType, String itemId, String imageUrl) {
        return new VoteItemSnapshot(imageUrl, null, null);
    }
}
