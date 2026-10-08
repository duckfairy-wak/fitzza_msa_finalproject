package com.fitzza.community.dto;

import com.fitzza.community.domain.VoteItemType;
import com.fitzza.community.domain.VoteOption;
import com.fitzza.community.domain.VoteOptionSource;

public record VoteOptionResponse(
        Long voteOptionId,
        String label,
        VoteOptionSource source,
        VoteItemType itemType,
        String itemId,
        String imageUrl,
        String name,
        Integer price) {

    public static VoteOptionResponse from(VoteOption option) {
        return new VoteOptionResponse(
                option.getId(),
                option.getLabel(),
                option.getSource(),
                option.getItemType(),
                option.getItemId(),
                option.getImageUrl(),
                option.getSnapshotName(),
                option.getSnapshotPrice());
    }
}
