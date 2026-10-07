package com.fitzza.user;

import java.time.Instant;
import java.util.Map;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@SpringBootApplication
public class UserServiceApplication {
    public static void main(String[] args) { SpringApplication.run(UserServiceApplication.class, args); }

    @RestController
    @RequestMapping("/api/v1/users")
    static class StatusController {
        @GetMapping("/status")
        Map<String, Object> status() { return Map.of("service", "user-service", "status", "UP", "timestamp", Instant.now()); }
    }
}
