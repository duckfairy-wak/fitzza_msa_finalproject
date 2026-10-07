package com.fitzza.notification;

import java.time.Instant;
import java.util.Map;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@SpringBootApplication
public class NotificationServiceApplication {
    public static void main(String[] args) { SpringApplication.run(NotificationServiceApplication.class, args); }
    @RestController @RequestMapping("/api/v1/notifications")
    static class StatusController {
        @GetMapping("/status") Map<String, Object> status() { return Map.of("service", "notification-service", "status", "UP", "timestamp", Instant.now()); }
    }
}
