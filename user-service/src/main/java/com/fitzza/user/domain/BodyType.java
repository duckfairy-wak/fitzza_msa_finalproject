package com.fitzza.user.domain;

public enum BodyType {
    SLIM("마른 체형"),
    STANDARD("보통 체형"),
    MUSCULAR("근육형"),
    CHUBBY("통통한 체형");

    private final String label;

    BodyType(String label) {
        this.label = label;
    }

    public String getLabel() {
        return label;
    }
}
