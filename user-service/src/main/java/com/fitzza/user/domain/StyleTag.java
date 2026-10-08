package com.fitzza.user.domain;

public enum StyleTag {
    CASUAL("캐주얼"),
    MINIMAL("미니멀"),
    STREET("스트릿"),
    FORMAL("포멀"),
    SPORTY("스포티"),
    VINTAGE("빈티지");

    private final String label;

    StyleTag(String label) {
        this.label = label;
    }

    public String getLabel() {
        return label;
    }
}
