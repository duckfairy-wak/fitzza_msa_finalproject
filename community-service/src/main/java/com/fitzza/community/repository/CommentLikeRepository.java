package com.fitzza.community.repository;

import com.fitzza.community.domain.CommentLike;
import com.fitzza.community.domain.CommentLikeId;
import java.util.Collection;
import java.util.List;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

public interface CommentLikeRepository extends JpaRepository<CommentLike, CommentLikeId> {

    // 같은 사용자가 동시에 두 번 눌러도 오류 없이 한 행만 남도록 DB의 충돌 무시 삽입을 쓴다.
    @Modifying
    @Query(
            value = "insert into comment_likes (comment_id, user_id, created_at) "
                    + "values (:commentId, :userId, now()) on conflict do nothing",
            nativeQuery = true)
    int insertIfAbsent(@Param("commentId") Long commentId, @Param("userId") Long userId);

    @Modifying
    @Query("delete from CommentLike l where l.id.commentId = :commentId and l.id.userId = :userId")
    int deleteLike(@Param("commentId") Long commentId, @Param("userId") Long userId);

    @Query("select count(l) from CommentLike l where l.id.commentId = :commentId")
    long countByCommentId(@Param("commentId") Long commentId);

    @Query("select new com.fitzza.community.repository.IdCount(l.id.commentId, count(l)) "
            + "from CommentLike l where l.id.commentId in :commentIds group by l.id.commentId")
    List<IdCount> countByCommentIds(@Param("commentIds") Collection<Long> commentIds);

    @Query("select l.id.commentId from CommentLike l "
            + "where l.id.userId = :userId and l.id.commentId in :commentIds")
    List<Long> findLikedCommentIds(
            @Param("userId") Long userId, @Param("commentIds") Collection<Long> commentIds);
}
