package com.fitzza.community.service;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

import com.fitzza.community.client.FittingResults;
import com.fitzza.community.client.FittingResults.FittingResult;
import com.fitzza.community.domain.Post;
import com.fitzza.community.domain.PostCategory;
import com.fitzza.community.domain.SharedSnapshot;
import com.fitzza.community.domain.SharedType;
import java.time.Duration;
import java.util.List;
import java.util.Optional;
import java.util.concurrent.atomic.AtomicLong;
import org.junit.jupiter.api.Test;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.web.client.ResourceAccessException;

class FittingImagesTest {

    private static final Long AUTHOR_ID = 7L;
    private static final Long OTHER_ID = 8L;

    private final FittingResults fittingResults = mock(FittingResults.class);
    private final FittingImages fittingImages = new FittingImages(fittingResults);

    // 글쓴이 ID로 물어본다. 같은 피팅을 공유한 글이 여러 개여도 한 번만 부른다.
    @Test
    void asksTheFittingServiceOncePerSharedFittingWithTheAuthorId() {
        Post first = fittingPost(1L, AUTHOR_ID, 70L);
        Post sameFitting = fittingPost(2L, OTHER_ID, 70L);
        Post another = fittingPost(3L, OTHER_ID, 71L);
        when(fittingResults.findFitting(eq(70L), eq(AUTHOR_ID), any(Duration.class))).thenReturn(completed("new-70"));
        when(fittingResults.findFitting(eq(71L), eq(OTHER_ID), any(Duration.class))).thenReturn(completed("new-71"));

        assertThat(fittingImages.latest(List.of(first, sameFitting, another)))
                .containsOnlyKeys(70L, 71L)
                .containsEntry(70L, "new-70")
                .containsEntry(71L, "new-71");
        verify(fittingResults, times(1)).findFitting(eq(70L), eq(AUTHOR_ID), any(Duration.class));
        verify(fittingResults, never()).findFitting(eq(70L), eq(OTHER_ID), any(Duration.class));
    }

    @Test
    void doesNotCallTheFittingServiceWithoutSharedFittings() {
        Post normal = post(1L, AUTHOR_ID);
        Post sharedProduct = post(2L, AUTHOR_ID);
        sharedProduct.attachShared(SharedType.PRODUCT, 56L, new SharedSnapshot(56L, "Fitzza", "셔츠", 39000, "old-56"));

        assertThat(fittingImages.latest(List.of(normal, sharedProduct))).isEmpty();
        verifyNoInteractions(fittingResults);
    }

    // 없어진 피팅, 완료되지 않은 피팅, 이미지가 빈 피팅은 저장된 주소를 쓰도록 빼 둔다.
    @Test
    void leavesOutMissingUnfinishedOrImagelessFittings() {
        when(fittingResults.findFitting(eq(70L), eq(AUTHOR_ID), any(Duration.class))).thenReturn(Optional.empty());
        when(fittingResults.findFitting(eq(71L), eq(AUTHOR_ID), any(Duration.class)))
                .thenReturn(Optional.of(new FittingResult(true, "PROCESSING", null, List.of())));
        when(fittingResults.findFitting(eq(72L), eq(AUTHOR_ID), any(Duration.class))).thenReturn(completed(" "));

        assertThat(fittingImages.latest(List.of(
                        fittingPost(1L, AUTHOR_ID, 70L), fittingPost(2L, AUTHOR_ID, 71L), fittingPost(3L, AUTHOR_ID, 72L))))
                .isEmpty();
    }

    // 한 번 실패하면 남은 피팅은 부르지 않고, 그때까지 받은 주소만 쓴다.
    @Test
    void stopsAskingAfterTheFirstFailureAndKeepsWhatItAlreadyGot() {
        when(fittingResults.findFitting(eq(70L), eq(AUTHOR_ID), any(Duration.class))).thenReturn(completed("new-70"));
        when(fittingResults.findFitting(eq(71L), eq(AUTHOR_ID), any(Duration.class))).thenThrow(new ResourceAccessException("vton down"));

        assertThat(fittingImages.latest(List.of(
                        fittingPost(1L, AUTHOR_ID, 70L), fittingPost(2L, AUTHOR_ID, 71L), fittingPost(3L, AUTHOR_ID, 72L))))
                .containsOnlyKeys(70L)
                .containsEntry(70L, "new-70");
        verify(fittingResults, never()).findFitting(eq(72L), eq(AUTHOR_ID), any(Duration.class));
    }

    // 실패 없이 느리기만 해도, 시간 예산을 다 쓰면 남은 피팅은 부르지 않고 그때까지 받은 주소만 쓴다.
    @Test
    void stopsAskingOnceTheTimeBudgetIsSpentAndKeepsWhatItAlreadyGot() {
        AtomicLong now = new AtomicLong();
        FittingImages budgeted = new FittingImages(fittingResults, now::get, Duration.ofSeconds(2));
        when(fittingResults.findFitting(eq(70L), eq(AUTHOR_ID), any(Duration.class))).thenAnswer(invocation -> {
            now.addAndGet(Duration.ofSeconds(1).toNanos());
            return completed("new-70");
        });
        when(fittingResults.findFitting(eq(71L), eq(AUTHOR_ID), any(Duration.class))).thenAnswer(invocation -> {
            now.addAndGet(Duration.ofSeconds(1).toNanos());
            return completed("new-71");
        });

        assertThat(budgeted.latest(List.of(
                        fittingPost(1L, AUTHOR_ID, 70L), fittingPost(2L, AUTHOR_ID, 71L), fittingPost(3L, AUTHOR_ID, 72L))))
                .containsOnlyKeys(70L, 71L)
                .containsEntry(70L, "new-70")
                .containsEntry(71L, "new-71");
        verify(fittingResults, never()).findFitting(eq(72L), eq(AUTHOR_ID), any(Duration.class));
    }

    // 호출마다 남은 예산만큼만 기다리게 한다. 첫 호출은 예산 전체, 다음 호출은 앞에서 쓰고 남은 만큼이다.
    @Test
    void waitsForEachCallOnlyAsLongAsTheBudgetThatIsLeft() {
        AtomicLong now = new AtomicLong();
        FittingImages budgeted = new FittingImages(fittingResults, now::get, Duration.ofSeconds(2));
        when(fittingResults.findFitting(70L, AUTHOR_ID, Duration.ofSeconds(2))).thenAnswer(invocation -> {
            now.addAndGet(Duration.ofMillis(1500).toNanos());
            return completed("new-70");
        });
        when(fittingResults.findFitting(71L, AUTHOR_ID, Duration.ofMillis(500))).thenReturn(completed("new-71"));

        assertThat(budgeted.latest(List.of(fittingPost(1L, AUTHOR_ID, 70L), fittingPost(2L, AUTHOR_ID, 71L))))
                .containsEntry(70L, "new-70")
                .containsEntry(71L, "new-71");
        verify(fittingResults).findFitting(71L, AUTHOR_ID, Duration.ofMillis(500));
    }

    private static Optional<FittingResult> completed(String resultImageUrl) {
        return Optional.of(new FittingResult(true, FittingResults.COMPLETED, resultImageUrl, List.of()));
    }

    private static Post fittingPost(Long postId, Long userId, Long fittingId) {
        Post post = post(postId, userId);
        post.attachShared(SharedType.FITTING, fittingId, new SharedSnapshot(null, null, null, null, "old-" + fittingId));
        return post;
    }

    private static Post post(Long postId, Long userId) {
        Post post = Post.createNormal(userId, "제목", "내용", PostCategory.DAILY);
        ReflectionTestUtils.setField(post, "id", postId);
        return post;
    }
}
