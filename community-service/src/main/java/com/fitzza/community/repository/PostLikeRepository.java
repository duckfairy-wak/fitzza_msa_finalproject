package com.fitzza.community.repository;

import com.fitzza.community.domain.PostLike;
import com.fitzza.community.domain.PostLikeId;
import java.util.Collection;
import java.util.List;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

public interface PostLikeRepository extends JpaRepository<PostLike, PostLikeId> {

    // 같은 사용자가 동시에 두 번 눌러도 오류 없이 한 행만 남도록 DB의 충돌 무시 삽입을 쓴다.
    @Modifying
    @Query(
            value = "insert into post_likes (post_id, user_id, created_at) "
                    + "values (:postId, :userId, now()) on conflict do nothing",
            nativeQuery = true)
    int insertIfAbsent(@Param("postId") Long postId, @Param("userId") Long userId);

    @Modifying
    @Query("delete from PostLike l where l.id.postId = :postId and l.id.userId = :userId")
    int deleteLike(@Param("postId") Long postId, @Param("userId") Long userId);

    @Query("select count(l) from PostLike l where l.id.postId = :postId")
    long countByPostId(@Param("postId") Long postId);

    @Query("select new com.fitzza.community.repository.IdCount(l.id.postId, count(l)) "
            + "from PostLike l where l.id.postId in :postIds group by l.id.postId")
    List<IdCount> countByPostIds(@Param("postIds") Collection<Long> postIds);
}
