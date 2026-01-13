package com.netadmin.agent.service;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;

@Service
public class RedisEventListener {

    private static final Logger logger = LoggerFactory.getLogger(RedisEventListener.class);
    private final DynamicSchedulerService schedulerService;

    public RedisEventListener(DynamicSchedulerService schedulerService) {
        this.schedulerService = schedulerService;
    }

    public void handleMessage(String message) {
        logger.info("Received Redis event: {}", message);
        
        if ("CONFIG_UPDATE:MONITORING".equals(message)) {
            schedulerService.refreshSchedule();
        }
    }
}
