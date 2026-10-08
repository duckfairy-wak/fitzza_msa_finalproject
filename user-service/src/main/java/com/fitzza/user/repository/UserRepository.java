package com.fitzza.user.repository;

import com.fitzza.user.domain.User;
import java.util.Optional;
import org.springframework.data.jpa.repository.JpaRepository;

public interface UserRepository extends JpaRepository<User, Long> {

    /**
     * 정규화된 이메일을 사용하는 계정이 상태와 무관하게 존재하는지 확인한다.
     *
     * @param email 호출자가 정규화한 이메일
     * @return 같은 이메일의 계정이 있으면 true
     */
    boolean existsByEmail(String email);

    /**
     * 닉네임을 사용하는 계정이 상태와 무관하게 존재하는지 확인한다.
     */
    boolean existsByNickname(String nickname);

    /**
     * 정규화된 이메일로 계정을 조회하며 활성 상태 검사는 호출자가 수행한다.
     *
     * @param email 호출자가 정규화한 이메일
     * @return 일치하는 계정 또는 빈 Optional
     */
    Optional<User> findByEmail(String email);
}
