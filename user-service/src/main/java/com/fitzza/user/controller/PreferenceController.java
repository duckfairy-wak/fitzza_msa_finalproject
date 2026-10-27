package com.fitzza.user.controller;

import com.fitzza.user.domain.FitType;
import com.fitzza.user.domain.StyleTag;
import com.fitzza.user.dto.PreferenceOptionResponse;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import java.util.Arrays;
import java.util.List;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@Tag(name = "취향", description = "선택 가능한 핏과 스타일 목록")
@RestController
@RequestMapping({"/users/preferences", "/api/users/preferences"})
public class PreferenceController {

    @Operation(summary = "핏 선택 목록 조회", description = "선언된 순서대로 label과 value 배열을 반환한다.")
    @GetMapping("/fits")
    public List<PreferenceOptionResponse> getFits() {
        return Arrays.stream(FitType.values())
                .map(fit -> new PreferenceOptionResponse(fit.getLabel(), fit.name()))
                .toList();
    }

    @Operation(summary = "스타일 선택 목록 조회", description = "선언된 순서대로 label과 value 배열을 반환한다.")
    @GetMapping("/styles")
    public List<PreferenceOptionResponse> getStyles() {
        return Arrays.stream(StyleTag.values())
                .map(style -> new PreferenceOptionResponse(style.getLabel(), style.name()))
                .toList();
    }
}
