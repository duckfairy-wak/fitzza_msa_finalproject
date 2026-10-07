package com.fitzza.user.service;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fitzza.user.domain.Gender;
import com.fitzza.user.domain.UserBodyUpdate;
import com.fitzza.user.exception.ErrorCode;
import com.fitzza.user.exception.UserApiException;
import java.util.List;
import org.junit.jupiter.api.Test;

class UserBodyUpdateParserTest {

    private final ObjectMapper objectMapper = new ObjectMapper();
    private final UserBodyUpdateParser parser = new UserBodyUpdateParser();

    @Test
    void readsEveryFieldThatWasSent() throws JsonProcessingException {
        UserBodyUpdate update = parser.parse(json("""
                {
                  "height": 172.5,
                  "weight": 64,
                  "gender": "W",
                  "bodyType": "STANDARD",
                  "preferredFit": "OVERSIZED",
                  "preferredStyles": ["CASUAL", "MINIMAL", "CASUAL"],
                  "shoeSize": 245
                }
                """));

        assertThat(update.height().value()).isEqualTo(172.5f);
        assertThat(update.weight().value()).isEqualTo(64f);
        assertThat(update.gender().value()).isEqualTo(Gender.W);
        assertThat(update.bodyType().value()).isEqualTo("STANDARD");
        assertThat(update.preferredFit().value()).isEqualTo("OVERSIZED");
        assertThat(update.preferredStyles().value()).isEqualTo(List.of("CASUAL", "MINIMAL"));
        assertThat(update.shoeSize().value()).isEqualTo(245);
    }

    @Test
    void distinguishesMissingFieldFromExplicitNull() throws JsonProcessingException {
        UserBodyUpdate update = parser.parse(json("""
                {"height": null, "preferredStyles": null}
                """));

        assertThat(update.height().present()).isTrue();
        assertThat(update.height().value()).isNull();
        assertThat(update.preferredStyles().present()).isTrue();
        assertThat(update.preferredStyles().value()).isNull();
        assertThat(update.weight().present()).isFalse();
        assertThat(update.gender().present()).isFalse();
        assertThat(update.bodyType().present()).isFalse();
        assertThat(update.preferredFit().present()).isFalse();
        assertThat(update.shoeSize().present()).isFalse();
    }

    @Test
    void acceptsValuesAtRangeBoundaries() throws JsonProcessingException {
        UserBodyUpdate update = parser.parse(json("""
                {"height": 100, "weight": 300, "shoeSize": 150}
                """));

        assertThat(update.height().value()).isEqualTo(100f);
        assertThat(update.weight().value()).isEqualTo(300f);
        assertThat(update.shoeSize().value()).isEqualTo(150);
    }

    @Test
    void rejectsNumbersOutsideAllowedRange() {
        assertInvalid("""
                {"height": 99.9}
                """);
        assertInvalid("""
                {"weight": 300.1}
                """);
        assertInvalid("""
                {"shoeSize": 351}
                """);
    }

    @Test
    void rejectsWrongValueTypes() {
        assertInvalid("""
                {"height": "172"}
                """);
        assertInvalid("""
                {"shoeSize": 245.5}
                """);
        assertInvalid("""
                {"preferredStyles": "CASUAL"}
                """);
    }

    @Test
    void rejectsCodesThatAreNotOfferedAsOptions() {
        assertInvalid("""
                {"gender": "X"}
                """);
        assertInvalid("""
                {"bodyType": "UNKNOWN"}
                """);
        assertInvalid("""
                {"preferredFit": "regular"}
                """);
        assertInvalid("""
                {"preferredStyles": ["CASUAL", "UNKNOWN"]}
                """);
    }

    @Test
    void rejectsBodyThatIsNotJsonObject() {
        assertInvalid("""
                ["height", 172]
                """);
    }

    private void assertInvalid(String content) {
        assertThatThrownBy(() -> parser.parse(json(content)))
                .isInstanceOf(UserApiException.class)
                .extracting("errorCode")
                .isEqualTo(ErrorCode.INVALID_INPUT);
    }

    private JsonNode json(String content) throws JsonProcessingException {
        return objectMapper.readTree(content);
    }
}
