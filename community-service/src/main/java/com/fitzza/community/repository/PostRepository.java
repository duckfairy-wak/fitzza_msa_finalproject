package com.fitzza.community.repository;

import com.fitzza.community.domain.Post;
import jakarta.persistence.LockModeType;
import java.util.Optional;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.JpaSpecificationExecutor;
import org.springframework.data.jpa.repository.Lock;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

public interface PostRepository extends JpaRepository<Post, Long>, JpaSpecificationExecutor<Post> {

    Optional<Post> findByIdAndDeletedAtIsNull(Long id);

    boolean existsByIdAndDeletedAtIsNull(Long id);

    // 투표 접수와 조기 종료가 겹쳐도 종료 뒤에 표가 들어가지 않도록 글 행을 잠그고 읽는다.
    @Lock(LockModeType.PESSIMISTIC_WRITE)
    @Query("select p from Post p where p.id = :postId and p.deletedAt is null")
    Optional<Post> findVisibleForUpdate(@Param("postId") Long postId);

    // 동시에 여러 명이 읽어도 조회수가 빠지지 않도록 DB에서 바로 더한다.
    @Modifying(clearAutomatically = true)
    @Query("update Post p set p.viewCount = p.viewCount + 1 where p.id = :postId and p.deletedAt is null")
    int incrementViewCount(@Param("postId") Long postId);
}
