.PHONY: help build up down restart logs ps shell clean backup status commit push pull

# Colors for output
GREEN  := \033[0;32m
YELLOW := \033[0;33m
RED    := \033[0;31m
NC     := \033[0m # No Color

# Default target
.DEFAULT_GOAL := help

# --- HELP ---
help: ## Show this help message
	@echo "$(GREEN)NetAdmin Bot - Makefile Commands$(NC)"
	@echo ""
	@echo "$(YELLOW)Docker Compose:$(NC)"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | grep -E '(up|down|build|restart|logs|ps|shell)' | awk 'BEGIN {FS = ":.*?## "}; {printf "  $(GREEN)%-15s$(NC) %s\n", $$1, $$2}'
	@echo ""
	@echo "$(YELLOW)Git:$(NC)"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | grep -E '(commit|push|pull|status)' | awk 'BEGIN {FS = ":.*?## "}; {printf "  $(GREEN)%-15s$(NC) %s\n", $$1, $$2}'
	@echo ""
	@echo "$(YELLOW)Utilities:$(NC)"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | grep -E '(clean|backup|install|test)' | awk 'BEGIN {FS = ":.*?## "}; {printf "  $(GREEN)%-15s$(NC) %s\n", $$1, $$2}'
	@echo ""

# --- DOCKER COMPOSE ---
up: ## Start all services
	@echo "$(GREEN)Starting all services...$(NC)"
	docker-compose up -d
	@echo "$(GREEN)✓ Services started$(NC)"

down: ## Stop all services
	@echo "$(YELLOW)Stopping all services...$(NC)"
	docker-compose down
	@echo "$(GREEN)✓ Services stopped$(NC)"

build: ## Build all images
	@echo "$(GREEN)Building images...$(NC)"
	docker-compose build
	@echo "$(GREEN)✓ Build complete$(NC)"

rebuild: ## Rebuild and restart all services
	@echo "$(GREEN)Rebuilding and restarting...$(NC)"
	docker-compose up --build -d
	@echo "$(GREEN)✓ Rebuild complete$(NC)"

restart: ## Restart all services
	@echo "$(YELLOW)Restarting services...$(NC)"
	docker-compose restart
	@echo "$(GREEN)✓ Services restarted$(NC)"

logs: ## Show logs from all services
	docker-compose logs -f

logs-redmine: ## Show Redmine logs
	docker-compose logs -f redmine

logs-bot: ## Show Python bot logs
	docker-compose logs -f python-bot

logs-agent: ## Show Java agent logs
	docker-compose logs -f java-agent

logs-nginx: ## Show Nginx logs
	docker-compose logs -f nginx

ps: ## Show running containers
	docker-compose ps

shell-redmine: ## Open shell in Redmine container
	docker-compose exec redmine /bin/bash

shell-bot: ## Open shell in Python bot container
	docker-compose exec python-bot /bin/bash

shell-agent: ## Open shell in Java agent container
	docker-compose exec java-agent /bin/sh

shell-db: ## Open PostgreSQL shell
	docker-compose exec db psql -U $$(grep POSTGRES_USER .env | cut -d '=' -f2) -d $$(grep POSTGRES_DB .env | cut -d '=' -f2)

# --- GIT ---
commit: ## Git commit (usage: make commit MSG="your message")
	@if [ -z "$(MSG)" ]; then \
		echo "$(RED)Error: MSG is required$(NC)"; \
		echo "Usage: make commit MSG=\"your commit message\""; \
		exit 1; \
	fi
	@echo "$(GREEN)Committing changes...$(NC)"
	git add -A
	git commit -m "$(MSG)"
	@echo "$(GREEN)✓ Committed: $(MSG)$(NC)"

push: ## Push to remote
	@echo "$(GREEN)Pushing to remote...$(NC)"
	git push
	@echo "$(GREEN)✓ Pushed$(NC)"

pull: ## Pull from remote
	@echo "$(GREEN)Pulling from remote...$(NC)"
	git pull
	@echo "$(GREEN)✓ Pulled$(NC)"

status: ## Show git status
	git status

# --- COMBINED GIT COMMANDS ---
save: commit push ## Commit and push (usage: make save MSG="message")
	@echo "$(GREEN)✓ Saved and pushed$(NC)"

# --- UTILITIES ---
clean: ## Remove stopped containers and unused images
	@echo "$(YELLOW)Cleaning Docker...$(NC)"
	docker-compose down -v
	docker system prune -f
	@echo "$(GREEN)✓ Cleaned$(NC)"

clean-all: ## Remove everything including volumes
	@echo "$(RED)WARNING: This will remove all containers, images, and volumes!$(NC)"
	@read -p "Are you sure? [y/N] " -n 1 -r; \
	echo; \
	if [[ $$REPLY =~ ^[Yy]$$ ]]; then \
		docker-compose down -v --rmi all; \
		docker system prune -af --volumes; \
		echo "$(GREEN)✓ Everything cleaned$(NC)"; \
	fi

backup: ## Create backup of database and files
	@echo "$(GREEN)Creating backup...$(NC)"
	@mkdir -p backups
	docker-compose exec -T db pg_dump -U $$(grep POSTGRES_USER .env | cut -d '=' -f2) $$(grep POSTGRES_DB .env | cut -d '=' -f2) > backups/db_backup_$$(date +%Y%m%d_%H%M%S).sql
	@echo "$(GREEN)✓ Backup created in backups/$(NC)"

install: ## Install/update dependencies (for local development)
	@echo "$(GREEN)Installing dependencies...$(NC)"
	@if [ -f "python-bot/requirements.txt" ]; then \
		echo "Installing Python dependencies..."; \
		pip install -r python-bot/requirements.txt; \
	fi
	@echo "$(GREEN)✓ Dependencies installed$(NC)"

test: ## Run tests (placeholder)
	@echo "$(YELLOW)Tests not configured yet$(NC)"

health: ## Check health of all services
	@echo "$(GREEN)Checking service health...$(NC)"
	@docker-compose ps
	@echo ""
	@echo "$(GREEN)Healthcheck status:$(NC)"
	@docker-compose ps --format "table {{.Name}}\t{{.Status}}" | grep -E "(healthy|unhealthy|starting)"

# --- QUICK COMMANDS ---
quick: rebuild ## Quick rebuild and restart (alias for rebuild)
	@echo "$(GREEN)✓ Quick rebuild done$(NC)"

stop: down ## Stop services (alias for down)

start: up ## Start services (alias for up)

# --- ENVIRONMENT ---
env-check: ## Check if .env file exists
	@if [ ! -f .env ]; then \
		echo "$(RED)Error: .env file not found!$(NC)"; \
		echo "Copy env.example to .env and fill in the values."; \
		exit 1; \
	else \
		echo "$(GREEN)✓ .env file exists$(NC)"; \
	fi

env-create: ## Create .env from env.example
	@if [ ! -f .env ]; then \
		cp env.example .env; \
		echo "$(GREEN)✓ Created .env from env.example$(NC)"; \
		echo "$(YELLOW)Please edit .env and fill in your values$(NC)"; \
	else \
		echo "$(RED).env already exists$(NC)"; \
	fi

# --- REDMINE SPECIFIC ---
redmine-migrate: ## Run Redmine migrations
	@echo "$(GREEN)Running Redmine migrations...$(NC)"
	docker-compose exec redmine bundle exec rake db:migrate RAILS_ENV=production
	docker-compose exec redmine bundle exec rake redmine:plugins:migrate RAILS_ENV=production
	@echo "$(GREEN)✓ Migrations complete$(NC)"

redmine-console: ## Open Redmine Rails console
	docker-compose exec redmine bundle exec rails console

redmine-plugins-sync: ## Copy plugins from source to storage directory
	@echo "$(GREEN)Syncing plugins to storage...$(NC)"
	@mkdir -p storage/redmine/plugins
	@cp -r redmine-service/plugins/* storage/redmine/plugins/ 2>/dev/null || true
	@echo "$(GREEN)✓ Plugins synced$(NC)"
	@echo "$(YELLOW)Restart Redmine to load plugins: make restart$(NC)"

# --- MONITORING ---
watch: ## Watch all logs in real-time
	watch -n 2 'docker-compose ps'

stats: ## Show container resource usage
	docker stats --format "table {{.Container}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.NetIO}}\t{{.BlockIO}}"

