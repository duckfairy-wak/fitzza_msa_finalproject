package com.fitzza.user.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.fitzza.user.domain.BodyType;
import com.fitzza.user.domain.FieldChange;
import com.fitzza.user.domain.FitType;
import com.fitzza.user.domain.Gender;
import com.fitzza.user.domain.StyleTag;
import com.fitzza.user.domain.UserBodyUpdate;
import com.fitzza.user.exception.ErrorCode;
import com.fitzza.user.exception.UserApiException;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Set;
import java.util.stream.Collectors;
import org.springframework.stereotype.Component;

// 요청 본문에 없는 필드는 그대로 두고 null로 온 필드만 지우려면 필드의 존재 여부를 알아야 해서 JSON 트리를 직접 읽는다.
@Component
public class UserBodyUpdateParser {

    static final double MIN_HEIGHT_CM = 100;
    static final double MAX_HEIGHT_CM = 250;
    static final double MIN_WEIGHT_KG = 20;
    static final double MAX_WEIGHT_KG = 300;
    static final int MIN_SHOE_SIZE_MM = 150;
    static final int MAX_SHOE_SIZE_MM = 350;

    private static final Set<String> GENDERS = namesOf(Gender.values());
    private static final Set<String> BODY_TYPES = namesOf(BodyType.values());
    private static final Set<String> FIT_TYPES = namesOf(FitType.values());
    private static final Set<String> STYLE_TAGS = namesOf(StyleTag.values());

    public UserBodyUpdate parse(JsonNode body) {
        if (body == null || !body.isObject()) {
            throw invalid("요청 본문은 JSON 객체여야 합니다.");
        }
        return new UserBodyUpdate(
                parseDecimal(body, "height", MIN_HEIGHT_CM, MAX_HEIGHT_CM),
                parseDecimal(body, "weight", MIN_WEIGHT_KG, MAX_WEIGHT_KG),
                parseGender(body),
                parseCode(body, "bodyType", BODY_TYPES),
                parseCode(body, "preferredFit", FIT_TYPES),
                parseCodes(body, "preferredStyles", STYLE_TAGS),
                parseInteger(body, "shoeSize", MIN_SHOE_SIZE_MM, MAX_SHOE_SIZE_MM));
    }

    private FieldChange<Float> parseDecimal(JsonNode body, String field, double min, double max) {
        if (!body.has(field)) {
            return FieldChange.absent();
        }
        JsonNode node = body.get(field);
        if (node.isNull()) {
            return FieldChange.of(null);
        }
        if (!node.isNumber() || node.asDouble() < min || node.asDouble() > max) {
            throw invalid(field + " 값은 " + formatNumber(min) + "~" + formatNumber(max) + " 사이의 숫자여야 합니다.");
        }
        return FieldChange.of((float) node.asDouble());
    }

    private FieldChange<Integer> parseInteger(JsonNode body, String field, int min, int max) {
        if (!body.has(field)) {
            return FieldChange.absent();
        }
        JsonNode node = body.get(field);
        if (node.isNull()) {
            return FieldChange.of(null);
        }
        if (!node.isIntegralNumber() || !node.canConvertToInt() || node.asInt() < min || node.asInt() > max) {
            throw invalid(field + " 값은 " + min + "~" + max + " 사이의 정수여야 합니다.");
        }
        return FieldChange.of(node.asInt());
    }

    private FieldChange<Gender> parseGender(JsonNode body) {
        FieldChange<String> code = parseCode(body, "gender", GENDERS);
        if (!code.present()) {
            return FieldChange.absent();
        }
        return FieldChange.of(code.value() == null ? null : Gender.valueOf(code.value()));
    }

    private FieldChange<String> parseCode(JsonNode body, String field, Set<String> allowedCodes) {
        if (!body.has(field)) {
            return FieldChange.absent();
        }
        JsonNode node = body.get(field);
        if (node.isNull()) {
            return FieldChange.of(null);
        }
        if (!node.isTextual() || !allowedCodes.contains(node.asText())) {
            throw invalid(field + " 값이 선택지에 없습니다.");
        }
        return FieldChange.of(node.asText());
    }

    private FieldChange<List<String>> parseCodes(JsonNode body, String field, Set<String> allowedCodes) {
        if (!body.has(field)) {
            return FieldChange.absent();
        }
        JsonNode node = body.get(field);
        if (node.isNull()) {
            return FieldChange.of(null);
        }
        if (!node.isArray()) {
            throw invalid(field + " 값은 배열이어야 합니다.");
        }
        Set<String> codes = new LinkedHashSet<>();
        for (JsonNode element : node) {
            if (!element.isTextual() || !allowedCodes.contains(element.asText())) {
                throw invalid(field + " 값이 선택지에 없습니다.");
            }
            codes.add(element.asText());
        }
        return FieldChange.of(new ArrayList<>(codes));
    }

    private String formatNumber(double value) {
        return String.valueOf((int) value);
    }

    private UserApiException invalid(String message) {
        return new UserApiException(ErrorCode.INVALID_INPUT, message);
    }

    private static Set<String> namesOf(Enum<?>[] values) {
        return Arrays.stream(values).map(Enum::name).collect(Collectors.toUnmodifiableSet());
    }
}
