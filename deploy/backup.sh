#!/usr/bin/env bash
# Run one backup now (the same one as every night at 03:15).
#   bash deploy/backup.sh
# The nightly schedule itself is the "backup" service of docker-compose: no cron or sudo needed.
cd "$(dirname "$0")/.." || exit 1
mkdir -p "$HOME/backups"
exec docker compose run --rm -T backup --now
