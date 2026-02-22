GITHUB_REPO := vicnasdev/drp

-include .env
export

.PHONY: help dev test migrate cleanup install set-domain

help: ## Show available commands
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-16s %s\n", $$1, $$2}'

# ── Server ────────────────────────────────────────────────────────────────────

dev: ## Start Django dev server
	python manage.py runserver

test: ## Run all tests
	pytest && python manage.py test core

migrate: ## Run migrations
	python manage.py migrate

cleanup: ## Delete expired drops (DB + B2)
	python manage.py cleanup

# ── CLI ───────────────────────────────────────────────────────────────────────

install: ## Install drp CLI locally (editable)
	pip install -e .

# ── Domain migration ──────────────────────────────────────────────────────────

set-domain: ## Swap default host: make set-domain NEW=drp.fyi
	@test -n "$(NEW)" || (echo "  ✗ Usage: make set-domain NEW=drp.fyi" && exit 1)
	old=$$(grep -oP "(?<=DEFAULT_HOST = 'https://).*(?=')" cli/__init__.py); \
	sed -i "s|https://$$old|https://$(NEW)|g" cli/__init__.py pyproject.toml
	link=$$(grep -oP '(?<=\*\*\[Live →\]\().*(?=\))' README.md); \
	sed -i "s|$${link}|https://$(NEW)|g" README.md
	@echo "  ✓ Code and README updated."
	@# ── GitHub webhook: create or update (all one shell to avoid exit code leaking) ──
	@{ \
	  if [ -z "$$GITHUB_ISSUES_TOKEN" ]; then \
	    echo "  ✗ GITHUB_ISSUES_TOKEN not set — skipping webhook"; \
	  else \
	    payload_url="https://$(NEW)/api/github-webhook/"; \
	    hook_id=$$(curl -s \
	      -H "Authorization: token $$GITHUB_ISSUES_TOKEN" \
	      -H "Accept: application/vnd.github+json" \
	      "https://api.github.com/repos/$$GITHUB_REPO/hooks" \
	      | grep -o '"id":[0-9]*' | head -1 | grep -o '[0-9]*'); \
	    if [ -n "$$hook_id" ]; then \
	      curl -s -X PATCH \
	        -H "Authorization: token $$GITHUB_ISSUES_TOKEN" \
	        -H "Accept: application/vnd.github+json" \
	        "https://api.github.com/repos/$$GITHUB_REPO/hooks/$$hook_id" \
	        -d "{\"config\":{\"url\":\"$$payload_url\",\"content_type\":\"json\",\"secret\":\"$$GITHUB_WEBHOOK_SECRET\"},\"active\":true}" \
	        > /dev/null && echo "  ✓ GitHub webhook updated → $$payload_url"; \
	    else \
	      curl -s -X POST \
	        -H "Authorization: token $$GITHUB_ISSUES_TOKEN" \
	        -H "Accept: application/vnd.github+json" \
	        "https://api.github.com/repos/$$GITHUB_REPO/hooks" \
	        -d "{\"name\":\"web\",\"active\":true,\"events\":[\"issues\"],\"config\":{\"url\":\"$$payload_url\",\"content_type\":\"json\",\"secret\":\"$$GITHUB_WEBHOOK_SECRET\"}}" \
	        > /dev/null && echo "  ✓ GitHub webhook created → $$payload_url"; \
	    fi; \
	  fi; \
	}