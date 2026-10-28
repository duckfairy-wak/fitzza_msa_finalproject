package com.fitzza.community.service;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.anyCollection;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

import com.fitzza.community.client.ProductCatalog;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collection;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.stream.LongStream;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.web.client.ResourceAccessException;

class ProductImagesTest {

    private final ProductCatalog productCatalog = mock(ProductCatalog.class);
    private final ProductImages productImages = new ProductImages(productCatalog);

    @Test
    void asksOnceForDistinctProductIdsAndSkipsMissingOnes() {
        when(productCatalog.findImageUrls(List.of(55L, 56L))).thenReturn(Map.of(55L, "new-55"));

        assertThat(productImages.latest(Arrays.asList(55L, null, 56L, 55L))).containsExactly(Map.entry(55L, "new-55"));
    }

    @Test
    void doesNotCallTheProductServiceWithoutProductIds() {
        assertThat(productImages.latest(Arrays.asList(null, null))).isEmpty();
        verifyNoInteractions(productCatalog);
    }

    // 상품 서비스 내부 일괄 조회는 한 번에 100개까지 받는다.
    @Test
    void splitsLargeLookupsIntoRequestsOfAtMostOneHundredIds() {
        List<Long> ids = LongStream.rangeClosed(1, 250).boxed().toList();
        when(productCatalog.findImageUrls(anyCollection())).thenAnswer(invocation -> {
            Map<Long, String> urls = new HashMap<>();
            for (Long id : invocation.<Collection<Long>>getArgument(0)) {
                urls.put(id, "new-" + id);
            }
            return urls;
        });

        Map<Long, String> latest = productImages.latest(ids);

        assertThat(latest).hasSize(250).containsEntry(250L, "new-250");
        @SuppressWarnings("unchecked")
        ArgumentCaptor<Collection<Long>> captor = ArgumentCaptor.forClass(Collection.class);
        verify(productCatalog, times(3)).findImageUrls(captor.capture());
        assertThat(new ArrayList<>(captor.getAllValues()))
                .extracting(Collection::size)
                .containsExactly(100, 100, 50);
    }

    // 이미지 주소를 못 받아도 글 조회는 막지 않는다. 빈 결과면 저장된 주소를 쓴다.
    @Test
    void returnsNothingWhenTheProductServiceIsDown() {
        when(productCatalog.findImageUrls(anyCollection())).thenThrow(new ResourceAccessException("down"));

        assertThat(productImages.latest(List.of(55L))).isEmpty();
    }
}
