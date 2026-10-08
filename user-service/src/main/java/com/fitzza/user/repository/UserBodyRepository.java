package com.fitzza.user.repository;

import com.fitzza.user.domain.UserBody;
import org.springframework.data.jpa.repository.JpaRepository;

public interface UserBodyRepository extends JpaRepository<UserBody, Long> {
}
