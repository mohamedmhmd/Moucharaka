#!/bin/sh
# Moucharaka backup, run by the "backup" service of docker-compose (no cron or sudo needed on the server).
#
#   --schedule   wait, and run every night at BACKUP_TIME (default 03:15, server time = UTC = Nouakchott)
#   --now        run one backup immediately (used by deploy/backup.sh)
#
# Each run: lock -> check disk -> dump database -> archive uploaded files -> copy .env -> verify
#           -> upload to BACKUP_BUCKET (Google Cloud Storage, with the VM's own access) -> delete old
#           local copies -> record the result in the back-office -> log line.
# Files land in /backups (= ~/backups on the server), named like the restore script expects.
set -u

BACKUP_DIR=/backups
KEEP_DAYS="${BACKUP_KEEP_DAYS:-14}"
BUCKET="${BACKUP_BUCKET:-}"; BUCKET="${BUCKET#gs://}"; BUCKET="${BUCKET%/}"
RUN_AT="${BACKUP_TIME:-03:15}"
MIN_FREE_KB=1048576
LOG="$BACKUP_DIR/backup.log"
LOCK="$BACKUP_DIR/.lock.d"
METADATA="http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token"

log() { echo "$(date '+%Y-%m-%d %H:%M:%S') $*" | tee -a "$LOG"; }
sql_quote() { printf "%s" "$1" | sed "s/'/''/g"; }

record() {  # record <ok|failed> <size> <uploaded true|false> <message>
  psql -q -v ON_ERROR_STOP=1 -c "INSERT INTO core_backuprun (created_at, stamp, status, size_bytes, uploaded, message)
    VALUES (now(), '$STAMP', '$1', $2, $3, '$(sql_quote "$4" | cut -c1-500)')" >/dev/null 2>&1 \
    || log "WARNING: could not record the result in the back-office"
}

owner_of_dir() { stat -L -c '%u:%g' "$BACKUP_DIR/"; }

upload() {  # upload <file>: Google Cloud Storage JSON API with the VM's service account token
  token="$(curl -fsS -H 'Metadata-Flavor: Google' "$METADATA" 2>/dev/null \
    | sed -n 's/.*"access_token" *: *"\([^"]*\)".*/\1/p')"
  [ -n "$token" ] || return 1
  name="$STAMP%2F$(basename "$1")"
  curl -fsS -o /dev/null -X POST -H "Authorization: Bearer $token" -H "Content-Type: application/octet-stream" \
    --data-binary "@$1" "https://storage.googleapis.com/upload/storage/v1/b/$BUCKET/o?uploadType=media&name=$name"
}

run_backup() {
  STAMP="$(date +%Y-%m-%d_%H%M)"
  DB="$BACKUP_DIR/db_$STAMP.dump"; FILES="$BACKUP_DIR/files_$STAMP.tar.gz"; ENVCOPY="$BACKUP_DIR/env_$STAMP"

  # 1. one backup at a time (a lock older than 6 hours is a leftover from a crash)
  if [ -d "$LOCK" ] && [ -n "$(find "$LOCK" -maxdepth 0 -mmin +360 2>/dev/null)" ]; then rmdir "$LOCK"; fi
  mkdir "$LOCK" 2>/dev/null || { log "SKIPPED $STAMP: another backup is still running"; return 0; }

  status=ok; message=""; size=0; uploaded=false; tables=0
  fail() { status=failed; message="$1"; rm -f "$DB.part" "$FILES.part"; }

  # 2. disk space
  free_kb="$(df -Pk "$BACKUP_DIR" | awk 'NR==2 {print $4}')"
  [ "${free_kb:-0}" -ge "$MIN_FREE_KB" ] || fail "less than 1 GB free on the server disk ($((free_kb / 1024)) MB left)"

  # 3. database (consistent snapshot while the site runs)
  if [ "$status" = ok ]; then
    if pg_dump -Fc > "$DB.part"; then mv "$DB.part" "$DB"; else fail "database dump failed"; fi
  fi
  # 4. uploaded files
  if [ "$status" = ok ]; then
    if tar czf "$FILES.part" -C /data media private_media; then mv "$FILES.part" "$FILES"
    else fail "file archive failed"; fi
  fi
  # 5. settings and secrets needed to restore
  if [ "$status" = ok ]; then cp /project.env "$ENVCOPY" 2>/dev/null || fail "could not copy .env"; fi
  # 6. verify
  if [ "$status" = ok ]; then
    tables="$(pg_restore --list "$DB" 2>/dev/null | grep -c 'TABLE DATA')"
    if [ ! -s "$DB" ] || [ ! -s "$FILES" ]; then fail "empty backup file"
    elif [ "${tables:-0}" -le 10 ]; then fail "database dump unreadable ($tables tables found)"
    elif ! tar -tzf "$FILES" >/dev/null 2>&1; then fail "file archive unreadable"
    else size=$(( $(stat -c %s "$DB") + $(stat -c %s "$FILES") )); fi
  fi
  if [ -f "$DB" ] || [ -f "$FILES" ]; then
    chmod 600 "$DB" "$FILES" "$ENVCOPY" 2>/dev/null
    chown "$(owner_of_dir)" "$DB" "$FILES" "$ENVCOPY" 2>/dev/null   # yours, not root's: you can delete them
  fi
  # 7. copy off the server
  if [ "$status" = ok ] && [ -n "$BUCKET" ]; then
    if upload "$DB" && upload "$FILES" && upload "$ENVCOPY"; then uploaded=true
    else message="saved on the server, but the copy to gs://$BUCKET failed (check the VM storage access)"; fi
  fi
  # 8. old local copies
  find "$BACKUP_DIR" -maxdepth 1 -type f \( -name 'db_*.dump' -o -name 'files_*.tar.gz' -o -name 'env_*' \) \
    -mtime +"$KEEP_DAYS" -delete
  # 9. record and log
  record "$status" "$size" "$uploaded" "$message"
  if [ "$status" = ok ]; then
    log "OK $STAMP: $tables tables, $((size / 1024)) KB, uploaded=$uploaded${message:+ ($message)}"
  else
    log "FAILED $STAMP: $message"
  fi
  chown "$(owner_of_dir)" "$LOG" 2>/dev/null
  rmdir "$LOCK"
  [ "$status" = ok ]
}

mkdir -p "$BACKUP_DIR"
command -v curl >/dev/null 2>&1 || apk add --no-cache curl >/dev/null 2>&1 || true

case "${1:---schedule}" in
  --now) run_backup ;;
  --schedule)
    echo "Backups scheduled every day at $RUN_AT (server time: $(date '+%H:%M')). Folder: ~/backups${BUCKET:+, copy to gs://$BUCKET}"
    last=""
    while true; do
      today="$(date +%Y-%m-%d)"
      if [ "$(date +%H:%M)" = "$RUN_AT" ] && [ "$last" != "$today" ]; then
        run_backup
        last="$today"
      fi
      sleep 30
    done ;;
  *) echo "usage: backup_container.sh --now | --schedule"; exit 2 ;;
esac
