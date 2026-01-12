package com.netadmin.agent.model;

import jakarta.persistence.*;

@Entity
@Table(name = "telegram_topics")
public class TelegramTopic {
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(unique = true, nullable = false)
    private String name;

    @Column(name = "thread_id", nullable = false)
    private Integer threadId;

    private String description;

    // Getters
    public String getName() { return name; }
    public Integer getThreadId() { return threadId; }
}

