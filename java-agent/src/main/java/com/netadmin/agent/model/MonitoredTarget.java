package com.netadmin.agent.model;

import jakarta.persistence.*;
import java.time.LocalDateTime;

@Entity
@Table(name = "monitored_targets")
public class MonitoredTarget {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    private String name;
    private String hostname;
    
    @Column(name = "interval_seconds")
    private Integer intervalSeconds;
    
    @Column(name = "is_active")
    private Boolean isActive;
    
    @Column(name = "last_status")
    private String lastStatus;
    
    @Column(name = "last_check")
    private LocalDateTime lastCheck;

    // Getters and Setters
    public Long getId() { return id; }
    public void setId(Long id) { this.id = id; }
    public String getName() { return name; }
    public void setName(String name) { this.name = name; }
    public String getHostname() { return hostname; }
    public void setHostname(String hostname) { this.hostname = hostname; }
    public Integer getIntervalSeconds() { return intervalSeconds; }
    public void setIntervalSeconds(Integer intervalSeconds) { this.intervalSeconds = intervalSeconds; }
    public Boolean getIsActive() { return isActive; }
    public void setIsActive(Boolean isActive) { this.isActive = isActive; }
    public String getLastStatus() { return lastStatus; }
    public void setLastStatus(String lastStatus) { this.lastStatus = lastStatus; }
    public LocalDateTime getLastCheck() { return lastCheck; }
    public void setLastCheck(LocalDateTime lastCheck) { this.lastCheck = lastCheck; }
}

