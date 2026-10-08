package com.fitzza.user.domain;

import java.util.function.Consumer;

// 부분 수정에서 "보내지 않은 필드"와 "null로 보내 지우려는 필드"를 구분한다.
public record FieldChange<T>(boolean present, T value) {

    public static <T> FieldChange<T> absent() {
        return new FieldChange<>(false, null);
    }

    public static <T> FieldChange<T> of(T value) {
        return new FieldChange<>(true, value);
    }

    public void ifPresent(Consumer<T> action) {
        if (present) {
            action.accept(value);
        }
    }
}
