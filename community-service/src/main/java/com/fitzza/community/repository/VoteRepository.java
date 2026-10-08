package com.fitzza.community.repository;

import com.fitzza.community.domain.Vote;
import java.util.List;
import java.util.Optional;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

public interface VoteRepository extends JpaRepository<Vote, String> {

    // 같은 사용자의 요청이 겹쳐도 오류 없이 한 표만 남도록 DB의 충돌 무시 삽입을 쓴다.
    @Modifying
    @Query(
            value = "insert into votes (vote_id, post_id, user_id, vote_option_id, created_at) "
                    + "values (:voteId, :postId, :userId, :voteOptionId, now()) on conflict do nothing",
            nativeQuery = true)
    int insertIfAbsent(
            @Param("voteId") String voteId,
            @Param("postId") Long postId,
            @Param("userId") Long userId,
            @Param("voteOptionId") Long voteOptionId);

    Optional<Vote> findByPostIdAndUserId(Long postId, Long userId);

    @Query("select new com.fitzza.community.repository.IdCount(v.voteOptionId, count(v)) "
            + "from Vote v where v.postId = :postId group by v.voteOptionId")
    List<IdCount> countByOption(@Param("postId") Long postId);
}
