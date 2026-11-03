package com.fitzza.community.repository;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.assertj.core.groups.Tuple.tuple;

import com.fitzza.community.domain.VoteItemType;
import com.fitzza.community.domain.VoteOption;
import com.fitzza.community.domain.VoteOptionSource;
import com.fitzza.community.support.PostgresModeJpaTest;
import java.util.List;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.dao.DataIntegrityViolationException;

@PostgresModeJpaTest
class VoteOptionRepositoryTest {

    private static final Long POST_ID = 10L;
    private static final Long OTHER_POST_ID = 11L;
    private static final String IMAGE_URL = "https://cdn.example.com/options/1.png";

    @Autowired
    private VoteOptionRepository voteOptionRepository;

    @Test
    void optionsComeBackInDisplayOrderForTheirPostOnly() {
        voteOptionRepository.saveAll(List.of(
                product(POST_ID, 2, "56"),
                product(POST_ID, 1, "55"),
                product(OTHER_POST_ID, 1, "55")));

        assertThat(voteOptionRepository.findByPostIdOrderByDisplayOrderAsc(POST_ID))
                .extracting(VoteOption::getItemId, VoteOption::getLabel)
                .containsExactly(
                        tuple("55", "A"),
                        tuple("56", "B"));
    }

    @Test
    void optionBelongsOnlyToThePostItWasCreatedFor() {
        VoteOption option = voteOptionRepository.save(product(POST_ID, 1, "55"));

        assertThat(voteOptionRepository.existsByIdAndPostId(option.getId(), POST_ID)).isTrue();
        assertThat(voteOptionRepository.existsByIdAndPostId(option.getId(), OTHER_POST_ID)).isFalse();
    }

    @Test
    void sameProductCannotBeAddedTwiceToOneVote() {
        voteOptionRepository.saveAndFlush(product(POST_ID, 1, "55"));

        assertThatThrownBy(() -> voteOptionRepository.saveAndFlush(product(POST_ID, 2, "55")))
                .isInstanceOf(DataIntegrityViolationException.class);
    }

    // 선택지를 통째로 바꿀 때 같은 표시 순서·같은 상품을 다시 넣어도 고유 제약에 걸리지 않아야 한다.
    @Test
    void optionsOfAPostCanBeDeletedAndWrittenAgain() {
        voteOptionRepository.saveAllAndFlush(List.of(product(POST_ID, 1, "55"), product(POST_ID, 2, "56")));
        voteOptionRepository.saveAndFlush(product(OTHER_POST_ID, 1, "55"));

        assertThat(voteOptionRepository.deleteByPostId(POST_ID)).isEqualTo(2);
        voteOptionRepository.saveAllAndFlush(List.of(product(POST_ID, 1, "56"), product(POST_ID, 2, "55")));

        assertThat(voteOptionRepository.findByPostIdOrderByDisplayOrderAsc(POST_ID))
                .extracting(VoteOption::getItemId, VoteOption::getLabel)
                .containsExactly(tuple("56", "A"), tuple("55", "B"));
        assertThat(voteOptionRepository.findByPostIdOrderByDisplayOrderAsc(OTHER_POST_ID)).hasSize(1);
    }

    @Test
    void firstOptionImagesComeBackOnlyForTheRequestedPosts() {
        voteOptionRepository.saveAll(List.of(
                option(POST_ID, 1, "https://cdn.example.com/a.png"),
                option(POST_ID, 2, "https://cdn.example.com/b.png"),
                option(OTHER_POST_ID, 1, "https://cdn.example.com/other.png"),
                option(30L, 1, "https://cdn.example.com/not-requested.png")));

        assertThat(voteOptionRepository.findFirstOptionImages(List.of(POST_ID, OTHER_POST_ID)))
                .containsExactlyInAnyOrder(
                        new PostImage(POST_ID, "https://cdn.example.com/a.png", VoteItemType.PRODUCT, "1"),
                        new PostImage(OTHER_POST_ID, "https://cdn.example.com/other.png", VoteItemType.PRODUCT, "1"));
    }

    // 선택지 이미지도 S3 Presigned URL이라 운영에서 2000자를 넘는 경우가 많다. 3000자까지 저장한다.
    @Test
    void anOptionKeepsPresignedImageUrlsLongerThanTwoThousandCharacters() {
        String longImageUrl = "https://bucket.s3.ap-northeast-2.amazonaws.com/product.jpg?" + "signature".repeat(300);
        VoteOption saved = voteOptionRepository.saveAndFlush(option(POST_ID, 1, longImageUrl));

        assertThat(longImageUrl.length()).isBetween(2001, VoteOption.IMAGE_URL_MAX_LENGTH);
        assertThat(voteOptionRepository.findById(saved.getId()).orElseThrow().getImageUrl()).isEqualTo(longImageUrl);
    }

    private static VoteOption option(Long postId, int displayOrder, String imageUrl) {
        return VoteOption.of(
                postId,
                displayOrder,
                VoteOptionSource.WISHLIST,
                VoteItemType.PRODUCT,
                String.valueOf(displayOrder),
                imageUrl,
                "셔츠",
                39000);
    }

    private static VoteOption product(Long postId, int displayOrder, String itemId) {
        return VoteOption.of(
                postId, displayOrder, VoteOptionSource.WISHLIST, VoteItemType.PRODUCT, itemId, IMAGE_URL, "셔츠", 39000);
    }
}
