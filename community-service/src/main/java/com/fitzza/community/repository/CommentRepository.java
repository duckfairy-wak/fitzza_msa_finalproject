package com.fitzza.community.repository;

import com.fitzza.community.domain.Comment;
import java.util.Collection;
import java.util.List;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

public interface CommentRepository extends JpaRepository<Comment, Long> {

    List<Comment> findByPostIdOrderByCreatedAtAscIdAsc(Long postId);

    long countByPostIdAndDeletedFalse(Long postId);

    @Query("select new com.fitzza.community.repository.IdCount(c.postId, count(c)) "
            + "from Comment c where c.postId in :postIds and c.deleted = false group by c.postId")
    List<IdCount> countActiveByPostIds(@Param("postIds") Collection<Long> postIds);
}
