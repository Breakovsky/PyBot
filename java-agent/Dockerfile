FROM maven:3.9-eclipse-temurin-21 AS build
WORKDIR /app
COPY pom.xml .
COPY src ./src
RUN mvn clean package -DskipTests

FROM eclipse-temurin:21-jre-alpine
WORKDIR /app
COPY --from=build /app/target/*.jar app.jar

# Directory for MDaemon semaphores
RUN mkdir -p /app/mdaemon_trigger

# Add healthcheck support
RUN apk add --no-cache curl

ENTRYPOINT ["java", "-jar", "app.jar"]
