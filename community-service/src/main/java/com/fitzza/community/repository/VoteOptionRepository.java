package com.fitzza.community.repository;

import com.fitzza.community.domain.VoteOption;
import java.util.List;
import org.springframework.data.jpa.repository.JpaRepository;

public interface VoteOptionRepository extends JpaRepository<VoteOption, Long> {

    List<VoteOption> findByPostIdOrderByDisplayOrderAsc(Long postId);

    boolean existsByIdAndPostId(Long id, Long postId);
}
