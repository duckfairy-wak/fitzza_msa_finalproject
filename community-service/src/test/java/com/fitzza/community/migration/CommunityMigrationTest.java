package com.fitzza.community.migration;

import static org.assertj.core.api.Assertions.assertThat;

import java.sql.Connection;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Statement;
import java.util.LinkedHashMap;
import java.util.Map;
import org.flywaydb.core.Flyway;
import org.junit.jupiter.api.Test;
import org.testcontainers.containers.PostgreSQLContainer;
import org.testcontainers.junit.jupiter.Container;
import org.testcontainers.junit.jupiter.Testcontainers;

@Testcontainers(disabledWithoutDocker = true)
class CommunityMigrationTest {

    private static final String SCHEMA = "community_service";

    @Container
    private static final PostgreSQLContainer<?> POSTGRES = new PostgreSQLContainer<>("postgres:16-alpine");

    @Test
    void v2ExpandsSharedImageUrlColumnsToText() throws SQLException {
        migrateTo("1");
        assertThat(imageUrlColumnTypes()).containsExactlyInAnyOrderEntriesOf(Map.of(
                "posts.shared_image_url", "character varying",
                "post_shared_items.image_url", "character varying"));

        migrateTo("2");

        assertThat(imageUrlColumnTypes()).containsExactlyInAnyOrderEntriesOf(
                Map.of("posts.shared_image_url", "text", "post_shared_items.image_url", "text"));
    }

    private void migrateTo(String version) {
        Flyway.configure()
                .dataSource(POSTGRES.getJdbcUrl(), POSTGRES.getUsername(), POSTGRES.getPassword())
                .schemas(SCHEMA)
                .defaultSchema(SCHEMA)
                .target(version)
                .load()
                .migrate();
    }

    private Map<String, String> imageUrlColumnTypes() throws SQLException {
        String query = """
                select table_name, column_name, data_type
                from information_schema.columns
                where table_schema = 'community_service'
                  and (table_name, column_name) in (
                      ('posts', 'shared_image_url'),
                      ('post_shared_items', 'image_url')
                  )
                order by table_name, column_name
                """;
        Map<String, String> columnTypes = new LinkedHashMap<>();
        try (Connection connection = POSTGRES.createConnection("");
                Statement statement = connection.createStatement();
                ResultSet result = statement.executeQuery(query)) {
            while (result.next()) {
                columnTypes.put(
                        result.getString("table_name") + "." + result.getString("column_name"),
                        result.getString("data_type"));
            }
        }
        return columnTypes;
    }
}
