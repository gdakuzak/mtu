.PHONY: build redeploy logs update setup-auto-update remove-auto-update release-patch release-minor release-major _check-clean

# --- Deploy ---

build:
	docker compose build

redeploy: build
	docker compose up -d
	@echo ""
	@echo ">> Deployed. Logs: make logs"

logs:
	docker compose logs -f mtu

# --- Update (for users who cloned the repo) ---
# Inspired by oh-my-zsh: timestamp-gated checks, version diff on update

update:
	@FORCE=1 bash scripts/auto-update.sh

setup-auto-update:
	@CRON_LINE="0 * * * * cd $(CURDIR) && bash scripts/auto-update.sh >> auto-update.log 2>&1"; \
	( crontab -l 2>/dev/null | grep -v "mtu/scripts/auto-update.sh" ; echo "$$CRON_LINE" ) | crontab -
	@echo ">> Auto-update installed (checks every hour, updates every MTU_UPDATE_DAYS days [default 7])"
	@echo "   Verify: crontab -l"

remove-auto-update:
	@crontab -l 2>/dev/null | grep -v "mtu/scripts/auto-update.sh" | crontab -
	@echo ">> Auto-update removed"

# --- Release ---
# Usage: make release-patch | release-minor | release-major

release-patch: _check-clean
	@bash scripts/release.sh patch
	$(MAKE) redeploy

release-minor: _check-clean
	@bash scripts/release.sh minor
	$(MAKE) redeploy

release-major: _check-clean
	@bash scripts/release.sh major
	$(MAKE) redeploy

# --- Guard: require clean working tree before release ---
_check-clean:
	@git diff --quiet && git diff --staged --quiet \
		|| (echo "ERROR: uncommitted changes — commit or stash first"; exit 1)
