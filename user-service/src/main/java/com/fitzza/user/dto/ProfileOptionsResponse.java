package com.fitzza.user.dto;

import java.util.List;

public record ProfileOptionsResponse(
        List<OptionResponse> bodyTypes,
        List<OptionResponse> fits,
        List<OptionResponse> styles) {
}
