#!/bin/bash

# ============================================================================
# Project Sanitation & Archiving Protocol
# ============================================================================
# This script cleans up the project root by:
# - Removing Python cache files and directories
# - Archiving legacy code and test artifacts
# - Consolidating log files
# - Preserving active components and protected data
# ============================================================================

set -e  # Exit on error
set -u  # Exit on undefined variable

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# ============================================================================
# Helper Functions
# ============================================================================

print_header() {
    echo -e "\n${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${BLUE}$1${NC}"
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}\n"
}

print_step() {
    echo -e "${YELLOW}▶${NC} $1"
}

print_success() {
    echo -e "${GREEN}✓${NC} $1"
}

print_error() {
    echo -e "${RED}✗${NC} $1"
}

# Calculate disk space usage of current directory
get_disk_usage() {
    du -sh . 2>/dev/null | cut -f1
}

# ============================================================================
# Main Cleanup Process
# ============================================================================

print_header "🧹 PROJECT CLEANUP SCRIPT 🧹"

# Get initial disk usage
print_step "Calculating initial disk space usage..."
INITIAL_SIZE=$(get_disk_usage)
echo -e "  ${BLUE}Initial size: ${INITIAL_SIZE}${NC}\n"

# ============================================================================
# A. THE "TRASH" - Delete Immediately
# ============================================================================

print_header "🗑️  PHASE 1: Removing Cache Files & System Junk"

# Remove __pycache__ directories
print_step "Removing __pycache__ directories..."
PYCACHE_COUNT=$(find . -type d -name "__pycache__" -not -path "./storage/*" -not -path "./_LEGACY_STORAGE/*" 2>/dev/null | wc -l)
if [ "$PYCACHE_COUNT" -gt 0 ]; then
    find . -type d -name "__pycache__" -not -path "./storage/*" -not -path "./_LEGACY_STORAGE/*" -exec rm -rf {} + 2>/dev/null || true
    print_success "Removed $PYCACHE_COUNT __pycache__ directory(ies)"
else
    print_success "No __pycache__ directories found"
fi

# Remove .pyc files
print_step "Removing .pyc files..."
PYC_COUNT=$(find . -type f -name "*.pyc" -not -path "./storage/*" -not -path "./_LEGACY_STORAGE/*" 2>/dev/null | wc -l)
if [ "$PYC_COUNT" -gt 0 ]; then
    find . -type f -name "*.pyc" -not -path "./storage/*" -not -path "./_LEGACY_STORAGE/*" -delete 2>/dev/null || true
    print_success "Removed $PYC_COUNT .pyc file(s)"
else
    print_success "No .pyc files found"
fi

# Remove .DS_Store files
print_step "Removing .DS_Store files..."
DSSTORE_COUNT=$(find . -type f -name ".DS_Store" -not -path "./storage/*" -not -path "./_LEGACY_STORAGE/*" 2>/dev/null | wc -l)
if [ "$DSSTORE_COUNT" -gt 0 ]; then
    find . -type f -name ".DS_Store" -not -path "./storage/*" -not -path "./_LEGACY_STORAGE/*" -delete 2>/dev/null || true
    print_success "Removed $DSSTORE_COUNT .DS_Store file(s)"
else
    print_success "No .DS_Store files found"
fi

# ============================================================================
# B. THE "ARCHIVE" - Move to _LEGACY_STORAGE
# ============================================================================

print_header "📦 PHASE 2: Archiving Legacy Code & Test Artifacts"

# Create _LEGACY_STORAGE directory
print_step "Creating _LEGACY_STORAGE directory..."
mkdir -p _LEGACY_STORAGE
print_success "_LEGACY_STORAGE directory created"

# Move OldProjects/
if [ -d "OldProjects" ]; then
    print_step "Moving OldProjects/ to _LEGACY_STORAGE/..."
    mv OldProjects _LEGACY_STORAGE/
    print_success "OldProjects/ archived"
else
    print_success "OldProjects/ not found (already archived or doesn't exist)"
fi

# Move v2_0.zip
if [ -f "v2_0.zip" ]; then
    print_step "Moving v2_0.zip to _LEGACY_STORAGE/..."
    mv v2_0.zip _LEGACY_STORAGE/
    print_success "v2_0.zip archived"
else
    print_success "v2_0.zip not found (already archived or doesn't exist)"
fi

# Move mock_mdaemon_app/
if [ -d "mock_mdaemon_app" ]; then
    print_step "Moving mock_mdaemon_app/ to _LEGACY_STORAGE/..."
    mv mock_mdaemon_app _LEGACY_STORAGE/
    print_success "mock_mdaemon_app/ archived"
else
    print_success "mock_mdaemon_app/ not found (already archived or doesn't exist)"
fi

# Handle backups/ directory
if [ -d "backups" ]; then
    print_step "Archiving backups/ directory..."
    # Count files in backups
    BACKUP_COUNT=$(find backups -type f 2>/dev/null | wc -l)
    if [ "$BACKUP_COUNT" -gt 0 ]; then
        # Move entire backups directory to archive
        mv backups _LEGACY_STORAGE/backups_$(date +%Y%m%d_%H%M%S)
        print_success "backups/ directory archived ($BACKUP_COUNT file(s))"
    else
        # Empty directory, just move it
        mv backups _LEGACY_STORAGE/backups_$(date +%Y%m%d_%H%M%S)
        print_success "backups/ directory archived (empty)"
    fi
else
    print_success "backups/ not found (already archived or doesn't exist)"
fi

# ============================================================================
# C. THE "LOGS" - Consolidate
# ============================================================================

print_header "📋 PHASE 3: Consolidating Log Files"

# Create logs/archive/ directory
print_step "Creating logs/archive/ directory..."
mkdir -p logs/archive
print_success "logs/archive/ directory created"

# Move localhost-*.log files from root
print_step "Moving localhost-*.log files from root to logs/archive/..."
LOGFILE_COUNT=0
for logfile in localhost-*.log; do
    if [ -f "$logfile" ]; then
        mv "$logfile" logs/archive/
        LOGFILE_COUNT=$((LOGFILE_COUNT + 1))
    fi
done

if [ "$LOGFILE_COUNT" -gt 0 ]; then
    print_success "Moved $LOGFILE_COUNT localhost-*.log file(s) to logs/archive/"
else
    print_success "No localhost-*.log files found in root"
fi

# Move test.log if it exists in root
if [ -f "test.log" ]; then
    print_step "Moving test.log to logs/archive/..."
    mv test.log logs/archive/
    print_success "test.log archived"
else
    print_success "test.log not found in root"
fi

# ============================================================================
# D. THE "ACTIVE" - Verification
# ============================================================================

print_header "✅ PHASE 4: Verifying Protected Directories"

# Verify protected directories still exist
PROTECTED_DIRS=("storage" "admin-panel" "python-bot" "java-agent" "redmine-service")
ALL_PROTECTED_OK=true

for dir in "${PROTECTED_DIRS[@]}"; do
    if [ -d "$dir" ]; then
        print_success "$dir/ is intact"
    else
        print_error "$dir/ is missing! (This should not happen)"
        ALL_PROTECTED_OK=false
    fi
done

# Verify protected files
PROTECTED_FILES=("docker-compose.yml" "Makefile" "env.example")
for file in "${PROTECTED_FILES[@]}"; do
    if [ -f "$file" ] || [ -e "$file" ]; then
        print_success "$file is intact"
    else
        print_success "$file not found (may not exist, which is OK)"
    fi
done

if [ "$ALL_PROTECTED_OK" = false ]; then
    print_error "WARNING: Some protected directories are missing!"
    exit 1
fi

# ============================================================================
# Final Summary
# ============================================================================

print_header "📊 CLEANUP SUMMARY"

# Get final disk usage
print_step "Calculating final disk space usage..."
FINAL_SIZE=$(get_disk_usage)
echo -e "  ${BLUE}Final size: ${FINAL_SIZE}${NC}"

# Show what was archived
echo -e "\n${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}✨ CLEANUP COMPLETE! ✨${NC}"
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}\n"

echo -e "${BLUE}Initial Size:${NC} ${INITIAL_SIZE}"
echo -e "${BLUE}Final Size:${NC}   ${FINAL_SIZE}"
echo -e "\n${GREEN}✓ Cache files removed${NC}"
echo -e "${GREEN}✓ Legacy code archived to _LEGACY_STORAGE/${NC}"
echo -e "${GREEN}✓ Log files consolidated to logs/archive/${NC}"
echo -e "${GREEN}✓ Protected directories and files preserved${NC}\n"

echo -e "${YELLOW}Note:${NC} Archived items are in _LEGACY_STORAGE/ and can be reviewed before deletion."
echo -e "${YELLOW}Note:${NC} Log files are in logs/archive/ and can be reviewed before deletion.\n"

