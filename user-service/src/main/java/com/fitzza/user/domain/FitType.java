package com.fitzza.user.domain;

// 추천 서비스가 상품의 fit_type과 그대로 비교하므로 상품 쪽 값과 같은 코드를 쓴다.
public enum FitType {
    REGULAR("레귤러"),
    RELAXED("릴렉스드"),
    SLIM("슬림"),
    OVERSIZED("오버사이즈"),
    CROPPED("크롭");

    private final String label;

    FitType(String label) {
        this.label = label;
    }

    public String getLabel() {
        return label;
    }
}
