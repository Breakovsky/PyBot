package com.netadmin.agent.repository;

import com.netadmin.agent.model.MonitoredTarget;
import org.springframework.data.jpa.repository.JpaRepository;
import java.util.List;

public interface MonitoredTargetRepository extends JpaRepository<MonitoredTarget, Long> {
    List<MonitoredTarget> findByIsActiveTrue();
}

