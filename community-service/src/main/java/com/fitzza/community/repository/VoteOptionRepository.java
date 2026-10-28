package com.fitzza.community.repository;

import com.fitzza.community.domain.VoteOption;
import java.util.Collection;
import java.util.List;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

public interface VoteOptionRepository extends JpaRepository<VoteOption, Long> {

    List<VoteOption> findByPostIdOrderByDisplayOrderAsc(Long postId);

    boolean existsByIdAndPostId(Long id, Long postId);

    // 선택지를 통째로 바꿀 때 쓴다. 엔티티 삭제는 flush 때 새 행 삽입보다 늦게 실행돼 (post_id, display_order)
    // 고유 제약에 걸리므로, 바로 실행되는 일괄 삭제로 먼저 지운다.
    @Modifying(flushAutomatically = true)
    @Query("delete from VoteOption o where o.postId = :postId")
    int deleteByPostId(@Param("postId") Long postId);

    // 목록 썸네일용으로 글마다 첫 번째 선택지(A)의 이미지를 한 번에 가져온다.
    @Query("select new com.fitzza.community.repository.PostImage(o.postId, o.imageUrl, o.itemType, o.itemId) from VoteOption o"
            + " where o.postId in :postIds and o.displayOrder = 1")
    List<PostImage> findFirstOptionImages(@Param("postIds") Collection<Long> postIds);
}
