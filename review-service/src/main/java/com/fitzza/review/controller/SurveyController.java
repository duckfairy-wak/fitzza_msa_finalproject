package com.fitzza.review.controller;

import com.fitzza.review.config.OpenApiConfig;
import com.fitzza.review.dto.ErrorResponse;
import com.fitzza.review.dto.SurveyCreateRequest;
import com.fitzza.review.dto.SurveyCreatedResponse;
import com.fitzza.review.dto.SurveyResponse;
import com.fitzza.review.security.AuthHeaders;
import com.fitzza.review.service.SurveyService;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.Parameter;
import io.swagger.v3.oas.annotations.media.Content;
import io.swagger.v3.oas.annotations.media.Schema;
import io.swagger.v3.oas.annotations.responses.ApiResponse;
import io.swagger.v3.oas.annotations.responses.ApiResponses;
import io.swagger.v3.oas.annotations.security.SecurityRequirement;
import io.swagger.v3.oas.annotations.tags.Tag;
import jakarta.validation.Valid;
import java.util.List;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.ResponseStatus;
import org.springframework.web.bind.annotation.RestController;

@Tag(name = "사이즈 설문", description = "구매한 상품의 사이즈 평가(작아요·잘 맞아요·커요). 모두 로그인이 필요하다.")
@SecurityRequirement(name = OpenApiConfig.BEARER_AUTH)
@RestController
@RequestMapping("/api/surveys")
public class SurveyController {

    private final SurveyService surveyService;

    public SurveyController(SurveyService surveyService) {
        this.surveyService = surveyService;
    }

    @Operation(
            summary = "사이즈 설문 작성",
            description = "내가 주문한(취소하지 않은) 주문 상품에만 쓸 수 있다. 주문 상품 하나에 한 번만 쓰고 수정할 수 없다.")
    @ApiResponses({
        @ApiResponse(responseCode = "201", description = "작성 성공"),
        @ApiResponse(
                responseCode = "400",
                description = "INVALID_REQUEST: 빈 값이나 없는 사이즈 평가",
                content = @Content(schema = @Schema(implementation = ErrorResponse.class))),
        @ApiResponse(
                responseCode = "401",
                description = "UNAUTHENTICATED: 로그인 필요",
                content = @Content(schema = @Schema(implementation = ErrorResponse.class))),
        @ApiResponse(
                responseCode = "403",
                description = "NOT_ORDER_OWNER: 남의 주문",
                content = @Content(schema = @Schema(implementation = ErrorResponse.class))),
        @ApiResponse(
                responseCode = "404",
                description = "ORDER_ITEM_NOT_FOUND: 없는 주문 상품",
                content = @Content(schema = @Schema(implementation = ErrorResponse.class))),
        @ApiResponse(
                responseCode = "409",
                description = "DUPLICATE_SURVEY: 이미 작성 / ORDER_CANCELED: 취소된 주문",
                content = @Content(schema = @Schema(implementation = ErrorResponse.class))),
        @ApiResponse(
                responseCode = "503",
                description = "ORDER_LOOKUP_UNAVAILABLE: 주문 서비스에서 주문을 확인하지 못함",
                content = @Content(schema = @Schema(implementation = ErrorResponse.class)))
    })
    @PostMapping
    @ResponseStatus(HttpStatus.CREATED)
    public SurveyCreatedResponse create(
            @Parameter(hidden = true) @RequestHeader(AuthHeaders.USER_ID) Long userId,
            @Valid @RequestBody SurveyCreateRequest request) {
        return surveyService.create(userId, request);
    }

    @Operation(
            summary = "내 설문 조회",
            description = "주문 내역 화면에서 주문 상품마다 설문을 썼는지 표시할 때 쓴다. orderItemIds는 쉼표로 1~100개. "
                    + "내가 쓴 설문만 돌려주고, 쓰지 않은 주문 상품은 결과에 없다.")
    @ApiResponses({
        @ApiResponse(responseCode = "200", description = "조회 성공"),
        @ApiResponse(
                responseCode = "400",
                description = "INVALID_REQUEST: orderItemIds가 없거나 100개 초과",
                content = @Content(schema = @Schema(implementation = ErrorResponse.class))),
        @ApiResponse(
                responseCode = "401",
                description = "UNAUTHENTICATED: 로그인 필요",
                content = @Content(schema = @Schema(implementation = ErrorResponse.class)))
    })
    @GetMapping("/me")
    public List<SurveyResponse> findMine(
            @Parameter(hidden = true) @RequestHeader(AuthHeaders.USER_ID) Long userId,
            @Parameter(description = "주문 상품 ID 목록(쉼표 구분)") @RequestParam("orderItemIds") List<Long> orderItemIds) {
        return surveyService.findMine(userId, orderItemIds);
    }
}
