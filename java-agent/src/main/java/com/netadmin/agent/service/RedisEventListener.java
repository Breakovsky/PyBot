package com.netadmin.agent.service;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.context.annotation.Bean;
import org.springframework.data.redis.connection.Message;
import org.springframework.data.redis.connection.MessageListener;
import org.springframework.data.redis.connection.RedisConnectionFactory;
import org.springframework.data.redis.listener.PatternTopic;
import org.springframework.data.redis.listener.RedisMessageListenerContainer;
import org.springframework.data.redis.listener.adapter.MessageListenerAdapter;
import org.springframework.stereotype.Service;

@Service
public class RedisEventListener {

    private static final Logger logger = LoggerFactory.getLogger(RedisEventListener.class);
    private final DynamicSchedulerService schedulerService;

    public RedisEventListener(DynamicSchedulerService schedulerService) {
        this.schedulerService = schedulerService;
    }

    @Bean
    RedisMessageListenerContainer container(RedisConnectionFactory connectionFactory,
                                          MessageListenerAdapter listenerAdapter) {
        RedisMessageListenerContainer container = new RedisMessageListenerContainer();
        container.setConnectionFactory(connectionFactory);
        container.addMessageListener(listenerAdapter, new PatternTopic("netadmin_events"));
        return container;
    }

    @Bean
    MessageListenerAdapter listenerAdapter() {
        return new MessageListenerAdapter(new MessageListener() {
            @Override
            public void onMessage(Message message, byte[] pattern) {
                String msg = new String(message.getBody());
                logger.info("Received Redis event: {}", msg);
                
                if ("CONFIG_UPDATE:MONITORING".equals(msg)) {
                    schedulerService.refreshSchedule();
                }
            }
        });
    }
}

