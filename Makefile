GITHUB_REPO := vicnasdev/drp

-include .env
export

.PHONY: help dev test migrate cleanup install \
        ollama-build ollama-run ollama-stop \
        issues issues-full issue close reopen issue-new

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

# ── Ollama (local) ────────────────────────────────────────────────────────────

OLLAMA_MODEL ?= qwen2.5:1.5b

ollama-build: ## Build Ollama Docker image
	docker build -t drp-ollama --build-arg OLLAMA_MODEL=$(OLLAMA_MODEL) ollama

ollama-run: ## Run Ollama locally on :11434
	docker run --rm -d --name drp-ollama \
	  -p 11434:11434 \
	  -e OLLAMA_MODEL=$(OLLAMA_MODEL) \
	  drp-ollama
	@echo "  ✓ Ollama running on http://localhost:11434"

ollama-stop: ## Stop local Ollama container
	docker stop drp-ollama 2>/dev/null || true

# ── GitHub Issues ─────────────────────────────────────────────────────────────
# Requires GITHUB_ISSUES_TOKEN in .env or environment.
# Usage:
#   make issues
#   make issues STATE=closed
#   make issues-full
#   make issue N=12
#   make issue-new TITLE="bug: crash" BODY="steps..."
#   make close N=12
#   make reopen N=12

define ISSUES_PY
import sys, json
issues = json.load(sys.stdin)
if not issues:
    print("  (none)")
else:
    for i in issues:
        labels = ", ".join(l["name"] for l in i.get("labels", []))
        tag = f"  [{labels}]" if labels else ""
        print(f"  #{i['number']:<5} {i['title']}{tag}")
endef

define ISSUES_FULL_PY
import sys, json
issues = json.load(sys.stdin)
if not issues:
    print("  (none)")
for i in issues:
    labels = ", ".join(l["name"] for l in i.get("labels", []))
    print(f"#{i['number']} [{i['state'].upper()}] {i['title']}")
    print(f"  opened by @{i['user']['login']}  |  comments: {i['comments']}")
    if labels: print(f"  labels: {labels}")
    print()
    print(i.get("body") or "(no description)")
    print()
    print(f"  {i['html_url']}")
    print("-" * 60)
endef

define ISSUE_PY
import sys, json
i = json.load(sys.stdin)
labels = ", ".join(l["name"] for l in i.get("labels", []))
print(f"#{i['number']} [{i['state'].upper()}] {i['title']}")
print(f"  opened by @{i['user']['login']}  |  comments: {i['comments']}")
if labels: print(f"  labels: {labels}")
print()
print(i.get("body") or "(no description)")
print()
print(f"  {i['html_url']}")
endef

export ISSUES_PY
export ISSUES_FULL_PY
export ISSUE_PY

_gh_check:
	@test -n "$$GITHUB_ISSUES_TOKEN" || (echo "  ✗ GITHUB_ISSUES_TOKEN not set" && exit 1)

issues: _gh_check ## List open issues (STATE=closed for closed)
	@curl -sf \
	  -H "Authorization: token $$GITHUB_ISSUES_TOKEN" \
	  -H "Accept: application/vnd.github+json" \
	  "https://api.github.com/repos/$(GITHUB_REPO)/issues?state=$(or $(STATE),open)&per_page=50" \
	  | python3 -c "$$ISSUES_PY"

issues-full: _gh_check ## List open issues with full detail (STATE=closed for closed)
	@curl -sf \
	  -H "Authorization: token $$GITHUB_ISSUES_TOKEN" \
	  -H "Accept: application/vnd.github+json" \
	  "https://api.github.com/repos/$(GITHUB_REPO)/issues?state=$(or $(STATE),open)&per_page=50" \
	  | python3 -c "$$ISSUES_FULL_PY"

issue: _gh_check ## Show a single issue: make issue N=12
	@test -n "$(N)" || (echo "  ✗ Usage: make issue N=<number>" && exit 1)
	@curl -sf \
	  -H "Authorization: token $$GITHUB_ISSUES_TOKEN" \
	  -H "Accept: application/vnd.github+json" \
	  "https://api.github.com/repos/$(GITHUB_REPO)/issues/$(N)" \
	  | python3 -c "$$ISSUE_PY"

issue-new: _gh_check ## Create an issue: make issue-new TITLE="..." BODY="..."
	@test -n "$(TITLE)" || (echo "  ✗ Usage: make issue-new TITLE=\"...\" BODY=\"...\"" && exit 1)
	@curl -sf -X POST \
	  -H "Authorization: token $$GITHUB_ISSUES_TOKEN" \
	  -H "Accept: application/vnd.github+json" \
	  "https://api.github.com/repos/$(GITHUB_REPO)/issues" \
	  -d "{\"title\": \"$(TITLE)\", \"body\": \"$(BODY)\"}" \
	  | python3 -c "import sys,json; i=json.load(sys.stdin); print(f\"  ✓ Created #{i['number']}: {i['title']}\n    {i['html_url']}\")"

close: _gh_check ## Close an issue: make close N=12
	@test -n "$(N)" || (echo "  ✗ Usage: make close N=<number>" && exit 1)
	@curl -sf -X PATCH \
	  -H "Authorization: token $$GITHUB_ISSUES_TOKEN" \
	  -H "Accept: application/vnd.github+json" \
	  "https://api.github.com/repos/$(GITHUB_REPO)/issues/$(N)" \
	  -d '{"state": "closed"}' \
	  | python3 -c "import sys,json; i=json.load(sys.stdin); print(f\"  ✓ Closed #{i['number']}: {i['title']}\")"

reopen: _gh_check ## Reopen an issue: make reopen N=12
	@test -n "$(N)" || (echo "  ✗ Usage: make reopen N=<number>" && exit 1)
	@curl -sf -X PATCH \
	  -H "Authorization: token $$GITHUB_ISSUES_TOKEN" \
	  -H "Accept: application/vnd.github+json" \
	  "https://api.github.com/repos/$(GITHUB_REPO)/issues/$(N)" \
	  -d '{"state": "open"}' \
	  | python3 -c "import sys,json; i=json.load(sys.stdin); print(f\"  ✓ Reopened #{i['number']}: {i['title']}\")"