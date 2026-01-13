package com.netadmin.agent.config;

import com.netadmin.agent.service.RedisEventListener;
import com.netadmin.agent.service.TaskListener;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.data.redis.connection.RedisConnectionFactory;
import org.springframework.data.redis.listener.PatternTopic;
import org.springframework.data.redis.listener.RedisMessageListenerContainer;
import org.springframework.data.redis.listener.adapter.MessageListenerAdapter;

@Configuration
public class RedisConfig {

    @Bean
    RedisMessageListenerContainer container(RedisConnectionFactory connectionFactory,
                                          MessageListenerAdapter taskListenerAdapter,
                                          MessageListenerAdapter eventListenerAdapter) {
        RedisMessageListenerContainer container = new RedisMessageListenerContainer();
        container.setConnectionFactory(connectionFactory);
        
        // Listen for Tasks
        container.addMessageListener(taskListenerAdapter, new PatternTopic("netadmin_tasks"));
        
        // Listen for Config Events
        container.addMessageListener(eventListenerAdapter, new PatternTopic("netadmin_events"));
        
        return container;
    }

    @Bean
    MessageListenerAdapter taskListenerAdapter(TaskListener listener) {
        return new MessageListenerAdapter(listener, "handleMessage");
    }

    @Bean
    MessageListenerAdapter eventListenerAdapter(RedisEventListener listener) {
        return new MessageListenerAdapter(listener, "handleMessage");
    }
}
