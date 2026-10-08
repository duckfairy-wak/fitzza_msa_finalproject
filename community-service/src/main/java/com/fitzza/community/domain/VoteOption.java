package com.fitzza.community.domain;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.EnumType;
import jakarta.persistence.Enumerated;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import jakarta.persistence.UniqueConstraint;

// 같은 상품·코디를 한 투표에 두 번 넣지 못하게 한다. 직접 올린 사진은 item_id가 NULL이라 제약에 걸리지 않는다.
@Entity
@Table(
        name = "vote_options",
        uniqueConstraints =
                @UniqueConstraint(
                        name = "uk_vote_options_post_item",
                        columnNames = {"post_id", "item_id", "item_type"}))
public class VoteOption {

    public static final int MIN_OPTIONS = 2;
    public static final int MAX_OPTIONS = 4;
    public static final int ITEM_ID_MAX_LENGTH = 100;
    public static final int IMAGE_URL_MAX_LENGTH = 500;

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    @Column(name = "vote_option_id")
    private Long id;

    @Column(name = "post_id", nullable = false, updatable = false)
    private Long postId;

    @Column(name = "item_id", length = ITEM_ID_MAX_LENGTH, updatable = false)
    private String itemId;

    @Enumerated(EnumType.STRING)
    @Column(name = "item_type", nullable = false, length = 20, updatable = false)
    private VoteItemType itemType;

    @Enumerated(EnumType.STRING)
    @Column(name = "source", nullable = false, length = 20, updatable = false)
    private VoteOptionSource source;

    @Column(name = "image_url", nullable = false, length = IMAGE_URL_MAX_LENGTH)
    private String imageUrl;

    // 상품명과 가격은 글을 쓴 시점의 값을 남긴다. 나중에 상품이 바뀌어도 투표 화면은 그대로다.
    @Column(name = "snapshot_name", length = 255)
    private String snapshotName;

    @Column(name = "snapshot_price")
    private Integer snapshotPrice;

    @Column(name = "display_order", nullable = false)
    private int displayOrder;

    protected VoteOption() {
    }

    public static VoteOption of(
            Long postId,
            int displayOrder,
            VoteOptionSource source,
            VoteItemType itemType,
            String itemId,
            String imageUrl,
            String snapshotName,
            Integer snapshotPrice) {
        VoteOption option = new VoteOption();
        option.postId = postId;
        option.displayOrder = displayOrder;
        option.source = source;
        option.itemType = itemType;
        option.itemId = itemId;
        option.imageUrl = imageUrl;
        option.snapshotName = snapshotName;
        option.snapshotPrice = snapshotPrice;
        return option;
    }

    // 화면에 보이는 선택지 구분(A, B, C, D). 표시 순서는 1부터 시작한다.
    public String getLabel() {
        return String.valueOf((char) ('A' + displayOrder - 1));
    }

    public Long getId() {
        return id;
    }

    public Long getPostId() {
        return postId;
    }

    public String getItemId() {
        return itemId;
    }

    public VoteItemType getItemType() {
        return itemType;
    }

    public VoteOptionSource getSource() {
        return source;
    }

    public String getImageUrl() {
        return imageUrl;
    }

    public String getSnapshotName() {
        return snapshotName;
    }

    public Integer getSnapshotPrice() {
        return snapshotPrice;
    }

    public int getDisplayOrder() {
        return displayOrder;
    }
}
