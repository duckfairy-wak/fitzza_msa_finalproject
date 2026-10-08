package com.fitzza.community.client;

import java.util.Collection;
import java.util.Map;

public interface UserDirectory {

    // 찾지 못한 사용자는 결과에서 빠진다.
    Map<Long, String> findNicknames(Collection<Long> userIds);
}
