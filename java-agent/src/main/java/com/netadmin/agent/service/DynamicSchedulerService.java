package com.netadmin.agent.service;

import com.netadmin.agent.model.MonitoredTarget;
import com.netadmin.agent.repository.MonitoredTargetRepository;
import jakarta.annotation.PostConstruct;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.scheduling.concurrent.ThreadPoolTaskScheduler;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ScheduledFuture;
import java.util.List;

/**
 * Dynamic Scheduler Service for network monitoring.
 * 
 * Thread Safety:
 * - Uses ConcurrentHashMap for scheduled tasks
 * - All DB operations are @Transactional
 * - Scheduler pool handles concurrent execution
 */
@Service
public class DynamicSchedulerService {

    private static final Logger logger = LoggerFactory.getLogger(DynamicSchedulerService.class);
    private static final DateTimeFormatter TIME_FORMATTER = DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss");

    private final MonitoredTargetRepository repository;
    private final AlertDispatcher alertDispatcher;
    private final NetworkService networkService;
    private final ThreadPoolTaskScheduler taskScheduler;
    private final Map<Long, ScheduledFuture<?>> scheduledTasks = new ConcurrentHashMap<>();

    public DynamicSchedulerService(
            MonitoredTargetRepository repository, 
            AlertDispatcher alertDispatcher,
            NetworkService networkService) {
        this.repository = repository;
        this.alertDispatcher = alertDispatcher;
        this.networkService = networkService;
        this.taskScheduler = new ThreadPoolTaskScheduler();
        this.taskScheduler.setPoolSize(10);
        this.taskScheduler.setThreadNamePrefix("DynamicScheduler-");
        this.taskScheduler.initialize();
    }

    @PostConstruct
    public void init() {
        logger.info("🚀 DynamicSchedulerService initialized");
        refreshSchedule();
    }

    public void refreshSchedule() {
        logger.info("🔄 Refreshing monitoring schedule...");
        
        // Cancel existing tasks
        int cancelledCount = scheduledTasks.size();
        scheduledTasks.values().forEach(future -> future.cancel(false));
        scheduledTasks.clear();
        
        if (cancelledCount > 0) {
            logger.info("Cancelled {} existing monitoring tasks", cancelledCount);
        }

        // Load active targets from DB
        List<MonitoredTarget> targets = repository.findByIsActiveTrue();
        logger.info("Found {} active targets to monitor", targets.size());
        
        for (MonitoredTarget target : targets) {
            scheduleTarget(target);
        }
        
        logger.info("✅ Monitoring schedule refreshed: {} targets active", targets.size());
    }

    private void scheduleTarget(MonitoredTarget target) {
        if (target.getIntervalSeconds() == null || target.getIntervalSeconds() <= 0) {
            logger.warn("Target {} has invalid interval, skipping", target.getName());
            return;
        }

        ScheduledFuture<?> future = taskScheduler.scheduleAtFixedRate(
                () -> performCheck(target.getId()),
                target.getIntervalSeconds() * 1000L
        );
        scheduledTasks.put(target.getId(), future);
        
        logger.info("📡 Scheduled monitoring: {} ({}) every {}s", 
            target.getName(), target.getHostname(), target.getIntervalSeconds());
    }

    /**
     * Perform health check for a target.
     * This method is called from scheduler threads - must be thread-safe.
     */
    @Transactional
    protected void performCheck(Long targetId) {
        repository.findById(targetId).ifPresent(target -> {
            String hostname = target.getHostname();
            String previousStatus = target.getLastStatus();
            LocalDateTime checkTime = LocalDateTime.now();
            
            try {
                // Use robust NetworkService ping
                boolean reachable = networkService.ping(hostname);
                String currentStatus = reachable ? "UP" : "DOWN";
                
                // Log ping result
                if (reachable) {
                    logger.debug("✓ {} ({}) is UP", target.getName(), hostname);
                } else {
                    logger.warn("✗ {} ({}) is DOWN", target.getName(), hostname);
                }
                
                // Alert Logic: State change detection
                if ("DOWN".equals(currentStatus) && !"DOWN".equals(previousStatus)) {
                    // Host just went down
                    String alertMessage = String.format(
                        "🚨 ALERT: Host %s (%s) is DOWN!\nTime: %s\nPrevious status: %s",
                        target.getName(),
                        hostname,
                        checkTime.format(TIME_FORMATTER),
                        previousStatus != null ? previousStatus : "UNKNOWN"
                    );
                    alertDispatcher.sendAlert("monitoring", alertMessage);
                    logger.error("🚨 Alert sent: {} is DOWN", target.getName());
                }
                
                // Recovery Logic: Host came back up
                if ("UP".equals(currentStatus) && "DOWN".equals(previousStatus)) {
                    String recoveryMessage = String.format(
                        "✅ RECOVERY: Host %s (%s) is back UP!\nTime: %s\nDowntime detected at: %s",
                        target.getName(),
                        hostname,
                        checkTime.format(TIME_FORMATTER),
                        target.getLastCheck() != null ? target.getLastCheck().format(TIME_FORMATTER) : "UNKNOWN"
                    );
                    alertDispatcher.sendAlert("monitoring", recoveryMessage);
                    logger.info("✅ Recovery sent: {} is back UP", target.getName());
                }
                
                // Update database
                target.setLastStatus(currentStatus);
                target.setLastCheck(checkTime);
                repository.save(target);
                
            } catch (Exception e) {
                logger.error("❌ Error checking {} ({}): {}", target.getName(), hostname, e.getMessage(), e);
                
                // Set ERROR status and alert if this is a new error state
                if (!"ERROR".equals(previousStatus)) {
                    String errorMessage = String.format(
                        "⚠️ ERROR: Unable to check host %s (%s)\nError: %s\nTime: %s",
                        target.getName(),
                        hostname,
                        e.getMessage(),
                        checkTime.format(TIME_FORMATTER)
                    );
                    alertDispatcher.sendAlert("monitoring", errorMessage);
                }
                
                target.setLastStatus("ERROR");
                target.setLastCheck(checkTime);
                repository.save(target);
            }
        });
    }
}
