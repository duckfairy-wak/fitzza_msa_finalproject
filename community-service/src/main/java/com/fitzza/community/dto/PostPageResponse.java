package com.fitzza.community.dto;

import java.util.List;

// page는 0부터 시작한다.
public record PostPageResponse(List<PostSummaryResponse> content, int page, int totalPages) {
}
