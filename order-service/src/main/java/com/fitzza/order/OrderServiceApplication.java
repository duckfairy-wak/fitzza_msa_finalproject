package com.fitzza.order;

import java.time.Instant;
import java.util.Map;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@SpringBootApplication
public class OrderServiceApplication {
    public static void main(String[] args) { SpringApplication.run(OrderServiceApplication.class, args); }

    @RestController
    @RequestMapping("/api/v1/orders")
    static class StatusController {
        @GetMapping("/status")
        Map<String, Object> status() { return Map.of("service", "order-service", "status", "UP", "timestamp", Instant.now()); }
    }
}
