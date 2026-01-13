package com.netadmin.agent.service;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;

import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStreamReader;
import java.net.InetAddress;
import java.util.concurrent.TimeUnit;

/**
 * Network utility service for host availability checks.
 * Provides robust ping functionality with fallback mechanisms.
 */
@Service
public class NetworkService {

    private static final Logger logger = LoggerFactory.getLogger(NetworkService.class);
    private static final int PING_TIMEOUT_MS = 3000;
    private static final String OS_NAME = System.getProperty("os.name").toLowerCase();

    /**
     * Ping a host using multi-method approach for reliability.
     * 
     * Strategy:
     * 1. Try Java InetAddress.isReachable() (fast but sometimes unreliable)
     * 2. If inconclusive, fallback to system ping command
     * 
     * @param hostname IP address or hostname
     * @return true if host is reachable, false otherwise
     */
    public boolean ping(String hostname) {
        if (hostname == null || hostname.trim().isEmpty()) {
            logger.warn("Ping called with empty hostname");
            return false;
        }

        hostname = hostname.trim();
        logger.debug("Pinging host: {}", hostname);

        // Method 1: InetAddress (quick check)
        boolean javaReachable = pingViaJava(hostname);
        
        if (javaReachable) {
            logger.debug("Host {} is reachable (Java method)", hostname);
            return true;
        }

        // Method 2: System ping (more reliable, but slower)
        logger.debug("Java ping failed for {}, trying system ping...", hostname);
        boolean systemReachable = pingViaSystem(hostname);
        
        if (systemReachable) {
            logger.debug("Host {} is reachable (System ping)", hostname);
            return true;
        }

        logger.debug("Host {} is NOT reachable (all methods failed)", hostname);
        return false;
    }

    /**
     * Ping using Java InetAddress.isReachable().
     * Fast but may fail due to firewall/ICMP restrictions.
     */
    private boolean pingViaJava(String hostname) {
        try {
            InetAddress address = InetAddress.getByName(hostname);
            boolean reachable = address.isReachable(PING_TIMEOUT_MS);
            logger.trace("InetAddress.isReachable({}) = {}", hostname, reachable);
            return reachable;
        } catch (Exception e) {
            logger.trace("Java ping failed for {}: {}", hostname, e.getMessage());
            return false;
        }
    }

    /**
     * Ping using system command (ping utility).
     * More reliable but requires external process.
     */
    private boolean pingViaSystem(String hostname) {
        try {
            // Build platform-specific ping command
            ProcessBuilder processBuilder;
            
            if (OS_NAME.contains("win")) {
                // Windows: ping -n 1 -w 3000 hostname
                processBuilder = new ProcessBuilder("ping", "-n", "1", "-w", String.valueOf(PING_TIMEOUT_MS), hostname);
            } else {
                // Linux/Unix: ping -c 1 -W 3 hostname
                int timeoutSeconds = PING_TIMEOUT_MS / 1000;
                processBuilder = new ProcessBuilder("ping", "-c", "1", "-W", String.valueOf(timeoutSeconds), hostname);
            }

            processBuilder.redirectErrorStream(true);
            Process process = processBuilder.start();

            // Wait for completion with timeout
            boolean finished = process.waitFor(PING_TIMEOUT_MS + 1000, TimeUnit.MILLISECONDS);
            
            if (!finished) {
                logger.warn("System ping timeout for {}", hostname);
                process.destroyForcibly();
                return false;
            }

            int exitCode = process.exitValue();
            
            // Read output for debugging
            if (logger.isTraceEnabled()) {
                try (BufferedReader reader = new BufferedReader(new InputStreamReader(process.getInputStream()))) {
                    String output = reader.lines().reduce("", (a, b) -> a + "\n" + b);
                    logger.trace("Ping output for {}: {}", hostname, output);
                }
            }

            // Exit code 0 means success
            boolean success = (exitCode == 0);
            logger.trace("System ping {} exit code: {} (success={})", hostname, exitCode, success);
            return success;

        } catch (IOException e) {
            logger.error("IO error during system ping for {}: {}", hostname, e.getMessage());
            return false;
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            logger.error("System ping interrupted for {}: {}", hostname, e.getMessage());
            return false;
        } catch (Exception e) {
            logger.error("Unexpected error during system ping for {}: {}", hostname, e.getMessage());
            return false;
        }
    }

    /**
     * Batch ping multiple hosts concurrently.
     * Useful for monitoring large networks.
     * 
     * @param hostnames Array of hostnames/IPs
     * @return Array of boolean results (same order as input)
     */
    public boolean[] pingBatch(String[] hostnames) {
        boolean[] results = new boolean[hostnames.length];
        
        for (int i = 0; i < hostnames.length; i++) {
            results[i] = ping(hostnames[i]);
        }
        
        return results;
    }

    /**
     * Resolve hostname to IP address.
     * Useful for monitoring logic.
     */
    public String resolveHostname(String hostname) {
        try {
            InetAddress address = InetAddress.getByName(hostname);
            return address.getHostAddress();
        } catch (Exception e) {
            logger.warn("Failed to resolve hostname {}: {}", hostname, e.getMessage());
            return hostname; // Return original if resolution fails
        }
    }
}

