package com.fitzza.user.dto;

import io.swagger.v3.oas.annotations.media.Schema;

public record PreferenceOptionResponse(
        @Schema(description = "화면에 표시할 한글 이름", example = "레귤러") String label,
        @Schema(description = "취향 저장에 사용할 코드", example = "REGULAR") String value) {}
