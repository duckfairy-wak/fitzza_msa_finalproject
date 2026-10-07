package com.fitzza.user.domain;

import java.util.List;

public record UserBodyUpdate(
        FieldChange<Float> height,
        FieldChange<Float> weight,
        FieldChange<Gender> gender,
        FieldChange<String> bodyType,
        FieldChange<String> preferredFit,
        FieldChange<List<String>> preferredStyles,
        FieldChange<Integer> shoeSize) {
}
