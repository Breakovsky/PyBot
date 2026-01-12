package com.netadmin.agent.service;

import com.netadmin.agent.model.MonitoredTarget;
import com.netadmin.agent.repository.MonitoredTargetRepository;
import jakarta.annotation.PostConstruct;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.scheduling.concurrent.ThreadPoolTaskScheduler;
import org.springframework.stereotype.Service;

import java.net.InetAddress;
import java.time.LocalDateTime;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ScheduledFuture;
import java.util.List;

@Service
public class DynamicSchedulerService {

    private static final Logger logger = LoggerFactory.getLogger(DynamicSchedulerService.class);

    private final MonitoredTargetRepository repository;
    private final AlertDispatcher alertDispatcher;
    private final ThreadPoolTaskScheduler taskScheduler;
    private final Map<Long, ScheduledFuture<?>> scheduledTasks = new ConcurrentHashMap<>();

    public DynamicSchedulerService(MonitoredTargetRepository repository, AlertDispatcher alertDispatcher) {
        this.repository = repository;
        this.alertDispatcher = alertDispatcher;
        this.taskScheduler = new ThreadPoolTaskScheduler();
        this.taskScheduler.setPoolSize(10);
        this.taskScheduler.setThreadNamePrefix("DynamicScheduler-");
        this.taskScheduler.initialize();
    }

    @PostConstruct
    public void init() {
        refreshSchedule();
    }

    public void refreshSchedule() {
        logger.info("Refreshing monitoring schedule...");
        scheduledTasks.values().forEach(future -> future.cancel(false));
        scheduledTasks.clear();

        List<MonitoredTarget> targets = repository.findByIsActiveTrue();
        for (MonitoredTarget target : targets) {
            scheduleTarget(target);
        }
    }

    private void scheduleTarget(MonitoredTarget target) {
        if (target.getIntervalSeconds() == null || target.getIntervalSeconds() <= 0) return;

        ScheduledFuture<?> future = taskScheduler.scheduleAtFixedRate(
                () -> performCheck(target.getId()),
                target.getIntervalSeconds() * 1000L
        );
        scheduledTasks.put(target.getId(), future);
    }

    private void performCheck(Long targetId) {
        repository.findById(targetId).ifPresent(target -> {
            try {
                InetAddress address = InetAddress.getByName(target.getHostname());
                boolean reachable = address.isReachable(2000);
                String status = reachable ? "UP" : "DOWN";
                
                // Alert Logic: Only alert on state change to DOWN
                if ("DOWN".equals(status) && !"DOWN".equals(target.getLastStatus())) {
                    alertDispatcher.sendAlert("monitoring", "🚨 ALERT: Host " + target.getName() + " (" + target.getHostname() + ") is DOWN!");
                }
                
                // Recovery Logic
                if ("UP".equals(status) && "DOWN".equals(target.getLastStatus())) {
                    alertDispatcher.sendAlert("monitoring", "✅ RECOVERY: Host " + target.getName() + " is back UP.");
                }

                logger.debug("Ping {}: {}", target.getHostname(), status);
                
                target.setLastStatus(status);
                target.setLastCheck(LocalDateTime.now());
                repository.save(target);
                
            } catch (Exception e) {
                logger.error("Error checking {}: {}", target.getHostname(), e.getMessage());
                target.setLastStatus("ERROR");
                repository.save(target);
            }
        });
    }
}
