package com.netadmin.agent.service;

import com.netadmin.agent.repository.TelegramTopicRepository;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Service;

@Service
public class AlertDispatcher {

    private static final Logger logger = LoggerFactory.getLogger(AlertDispatcher.class);
    private final StringRedisTemplate redisTemplate;
    private final TelegramTopicRepository topicRepository;

    public AlertDispatcher(StringRedisTemplate redisTemplate, TelegramTopicRepository topicRepository) {
        this.redisTemplate = redisTemplate;
        this.topicRepository = topicRepository;
    }

    public void sendAlert(String topicName, String message) {
        // We verify topic exists, but we push the NAME to Redis.
        // Python bot resolves the actual Thread ID to allow hot-swapping topics.
        try {
            String payload = topicName + "|" + message;
            redisTemplate.convertAndSend("bot_alerts", payload);
            logger.info("Dispatched alert to [{}]: {}", topicName, message);
        } catch (Exception e) {
            logger.error("Failed to dispatch alert", e);
        }
    }
}

