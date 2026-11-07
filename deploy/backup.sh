#!/usr/bin/env bash
# Moucharaka nightly backup: database + uploaded files + .env
#
#   bash deploy/backup.sh            # run now (also used by the nightly cron job)
#
# Steps: lock -> check disk -> dump database -> archive files -> copy .env -> verify
#        -> upload to the bucket (if BACKUP_BUCKET is set in .env) -> delete old local copies
#        -> record the result in the back-office (alerts the owners on failure) -> log line.
#
# Settings (optional, in .env):
#   BACKUP_BUCKET=gs://your-bucket-name   copy each backup there (needs storage access for the VM)
#   BACKUP_DIR=/home/you/backups          where local copies go (default: ~/backups)
#   BACKUP_KEEP_DAYS=14                   local copies older than this are deleted
set -uo pipefail
export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/snap/bin:$PATH"

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT" || exit 1

env_value() { grep -E "^$1=" .env 2>/dev/null | tail -1 | cut -d= -f2- | tr -d '"'"'"; }
BACKUP_DIR="${BACKUP_DIR:-$(env_value BACKUP_DIR)}"; BACKUP_DIR="${BACKUP_DIR:-$HOME/backups}"
KEEP_DAYS="${BACKUP_KEEP_DAYS:-$(env_value BACKUP_KEEP_DAYS)}"; KEEP_DAYS="${KEEP_DAYS:-14}"
BUCKET="${BACKUP_BUCKET:-$(env_value BACKUP_BUCKET)}"; BUCKET="${BUCKET%/}"
MIN_FREE_KB=1048576   # refuse to run with less than 1 GB free
STAMP="$(date +%Y-%m-%d_%H%M)"
LOG="$BACKUP_DIR/backup.log"

mkdir -p "$BACKUP_DIR" && chmod 700 "$BACKUP_DIR"
DB="$BACKUP_DIR/db_$STAMP.dump"
FILES="$BACKUP_DIR/files_$STAMP.tar.gz"
ENVCOPY="$BACKUP_DIR/env_$STAMP"

log() { echo "$(date '+%Y-%m-%d %H:%M:%S') $*" | tee -a "$LOG"; }

record() {  # record <ok|failed> <size> <uploaded:yes|no> <message>
  local extra=()
  [ "$3" = "yes" ] && extra+=(--uploaded)
  docker compose exec -T web python manage.py record_backup --status "$1" --stamp "$STAMP" --size "$2" \
    "${extra[@]}" --message "$4" >/dev/null 2>&1 || log "WARNING: could not record the result in the back-office"
}

fail() {
  log "FAILED $STAMP: $1"
  rm -f "$DB.part" "$FILES.part"
  record failed 0 no "$1"
  exit 1
}

# 1. One backup at a time
exec 9>"$BACKUP_DIR/.lock"
flock -n 9 || { log "SKIPPED $STAMP: another backup is still running"; exit 0; }

# 2. Enough disk space?
free_kb="$(df -Pk "$BACKUP_DIR" | awk 'NR==2 {print $4}')"
[ "${free_kb:-0}" -ge "$MIN_FREE_KB" ] || fail "less than 1 GB free on the server disk ($((free_kb / 1024)) MB left)"

# 3. Database (consistent snapshot while the site keeps running)
docker compose exec -T db pg_dump -U moucharaka -Fc moucharaka > "$DB.part" || fail "database dump failed"
mv "$DB.part" "$DB"

# 4. Uploaded files (ID documents, photos, receipts, attachments)
docker compose exec -T web tar czf - -C /data media private_media > "$FILES.part" || fail "file archive failed"
mv "$FILES.part" "$FILES"

# 5. Settings and secrets needed to restore
cp .env "$ENVCOPY" || fail "could not copy .env"
chmod 600 "$DB" "$FILES" "$ENVCOPY"

# 6. Verify that each file can be read back
[ -s "$DB" ] && [ -s "$FILES" ] || fail "empty backup file"
tables="$(docker compose exec -T db pg_restore --list < "$DB" 2>/dev/null | grep -c 'TABLE DATA' || true)"
[ "${tables:-0}" -gt 10 ] || fail "database dump unreadable ($tables tables found)"
tar -tzf "$FILES" >/dev/null 2>&1 || fail "file archive unreadable"
size=$(( $(stat -c %s "$DB") + $(stat -c %s "$FILES") ))

# 7. Copy off the server
uploaded=no
note=""
if [ -n "$BUCKET" ]; then
  if command -v gsutil >/dev/null 2>&1; then
    gsutil -q cp "$DB" "$FILES" "$ENVCOPY" "$BUCKET/$STAMP/" && uploaded=yes
  elif command -v gcloud >/dev/null 2>&1; then
    gcloud storage cp "$DB" "$FILES" "$ENVCOPY" "$BUCKET/$STAMP/" --quiet && uploaded=yes
  fi
  [ "$uploaded" = "yes" ] || note="saved on the server, but the copy to $BUCKET failed (check the VM storage access)"
fi

# 8. Delete old local copies
find "$BACKUP_DIR" -maxdepth 1 -type f \( -name 'db_*.dump' -o -name 'files_*.tar.gz' -o -name 'env_*' \) \
  -mtime +"$KEEP_DAYS" -delete

# 9. Record and log
record ok "$size" "$uploaded" "$note"
log "OK $STAMP: $tables tables, $((size / 1024)) KB, uploaded=$uploaded${note:+ ($note)}"
