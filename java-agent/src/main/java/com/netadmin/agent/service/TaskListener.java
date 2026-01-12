package com.netadmin.agent.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

import java.io.File;
import java.io.FileWriter;
import java.io.IOException;
import java.io.PrintWriter;
import java.time.Instant;

@Slf4j
@Service
@RequiredArgsConstructor
public class TaskListener {

    private final ObjectMapper objectMapper;

    @Value("${app.mdaemon.trigger-path}")
    private String mdaemonPath;

    public void handleMessage(String message) {
        log.info("Received message from Redis: {}", message);
        try {
            JsonNode root = objectMapper.readTree(message);
            String action = root.path("action").asText();
            
            if ("CREATE_USER".equalsIgnoreCase(action)) {
                handleCreateUser(root);
            } else if ("PING".equalsIgnoreCase(action)) {
                log.info("PING received. System is healthy.");
            } else {
                log.warn("Unknown action: {}", action);
            }
        } catch (Exception e) {
            log.error("Error processing message", e);
        }
    }

    private void handleCreateUser(JsonNode payload) {
        log.info("Processing CREATE_USER action. Payload: {}", payload);
        String username = payload.path("username").asText("unknown");
        
        // MDaemon usually expects a specific format. 
        // For this MVP, we create a dummy .SEM file with user details inside.
        // Format: ADDUSER.SEM
        // Content: "User: <username>"
        
        String filename = "ADDUSER_" + username + "_" + Instant.now().toEpochMilli() + ".SEM";
        File triggerFile = new File(mdaemonPath, filename);
        
        try (PrintWriter writer = new PrintWriter(new FileWriter(triggerFile))) {
            writer.println("Command: CreateUser");
            writer.println("Username: " + username);
            writer.println("Email: " + payload.path("payload").path("email").asText());
            writer.println("Created: " + Instant.now());
            
            log.info("Created MDaemon semaphore file: {}", triggerFile.getAbsolutePath());
        } catch (IOException e) {
            log.error("Failed to create semaphore file at {}", mdaemonPath, e);
        }
    }
}
