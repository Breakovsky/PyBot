package com.netadmin.agent.repository;

import com.netadmin.agent.model.TelegramTopic;
import org.springframework.data.jpa.repository.JpaRepository;
import java.util.Optional;

public interface TelegramTopicRepository extends JpaRepository<TelegramTopic, Long> {
    Optional<TelegramTopic> findByName(String name);
}

