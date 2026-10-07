FROM eclipse-temurin:21-jdk-alpine AS builder
ARG MODULE
WORKDIR /workspace
COPY . .
RUN chmod +x gradlew && ./gradlew :${MODULE}:bootJar --no-daemon

FROM eclipse-temurin:21-jre-alpine
ARG MODULE
WORKDIR /app
RUN addgroup -S fitzza && adduser -S fitzza -G fitzza
COPY --from=builder /workspace/${MODULE}/build/libs/*.jar app.jar
USER fitzza
ENTRYPOINT ["java", "-XX:MaxRAMPercentage=75.0", "-jar", "/app/app.jar"]
