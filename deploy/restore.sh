#!/usr/bin/env bash
# Moucharaka restore
#
#   bash deploy/restore.sh                       # list the available backups
#   bash deploy/restore.sh --check 2026-11-07_0315   # SAFE TEST: restore into a temporary database,
#                                                   # count users/projects, then delete it. Site untouched.
#   bash deploy/restore.sh 2026-11-07_0315        # REAL RESTORE: replaces the current data
#
# If the backup is not on this server but BACKUP_BUCKET is set in .env, it is downloaded first.
# Before a real restore, the current database is saved as pre-restore_<date>.dump, just in case.
set -uo pipefail
export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/snap/bin:$PATH"

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT" || exit 1
env_value() { grep -E "^$1=" .env 2>/dev/null | tail -1 | cut -d= -f2- | tr -d '"'"'"; }
BACKUP_DIR="${BACKUP_DIR:-$(env_value BACKUP_DIR)}"; BACKUP_DIR="${BACKUP_DIR:-$HOME/backups}"
BUCKET="${BACKUP_BUCKET:-$(env_value BACKUP_BUCKET)}"; BUCKET="${BUCKET%/}"

die() { echo "ERROR: $*" >&2; exit 1; }

wait_for_db() {
  for _i in $(seq 1 30); do
    docker compose exec -T db pg_isready -U moucharaka >/dev/null 2>&1 && return 0
    sleep 2
  done
  die "the database did not start"
}

CHECK=no
if [ "${1:-}" = "--check" ]; then CHECK=yes; shift; fi
STAMP="${1:-}"

if [ -z "$STAMP" ]; then
  echo "Backups on this server ($BACKUP_DIR):"
  ls -1 "$BACKUP_DIR" 2>/dev/null | sed -n 's/^db_\(.*\)\.dump$/  \1/p' | sort -r
  if [ -n "$BUCKET" ] && command -v gsutil >/dev/null 2>&1; then
    echo "Backups in $BUCKET:"
    gsutil ls "$BUCKET/" 2>/dev/null | sed -e "s|$BUCKET/||" -e 's|/$||' -e 's/^/  /' | sort -r
  fi
  echo
  echo "Test one safely:  bash deploy/restore.sh --check <name>"
  echo "Restore one:      bash deploy/restore.sh <name>"
  exit 0
fi

DB="$BACKUP_DIR/db_$STAMP.dump"
FILES="$BACKUP_DIR/files_$STAMP.tar.gz"
if [ ! -f "$DB" ] && [ -n "$BUCKET" ]; then
  echo "Downloading $STAMP from $BUCKET..."
  mkdir -p "$BACKUP_DIR"
  gsutil -q cp "$BUCKET/$STAMP/*" "$BACKUP_DIR/" || die "download from the bucket failed"
fi
[ -f "$DB" ] || die "backup $DB not found"
[ -f "$FILES" ] || die "backup $FILES not found"
[ -f .env ] || die "no .env here: put back the saved env_$STAMP as .env first (same passwords and secret key)"

docker compose up -d db >/dev/null 2>&1
wait_for_db

if [ "$CHECK" = "yes" ]; then
  echo "Test restore of $STAMP into a temporary database (the site is not touched)..."
  docker compose exec -T db dropdb -U moucharaka --if-exists restore_check >/dev/null 2>&1
  docker compose exec -T db createdb -U moucharaka restore_check || die "could not create the test database"
  docker compose exec -T db pg_restore -U moucharaka -d restore_check --no-owner < "$DB" 2>/dev/null
  q() { docker compose exec -T db psql -U moucharaka -d restore_check -tAc "$1" 2>/dev/null | tr -d '[:space:]'; }
  users="$(q 'select count(*) from accounts_user')"
  projects="$(q 'select count(*) from projects_project')"
  contracts="$(q 'select count(*) from contracts_contract' || echo '?')"
  docker compose exec -T db dropdb -U moucharaka restore_check >/dev/null 2>&1
  files="$(tar -tzf "$FILES" 2>/dev/null | grep -vc '/$')"
  [ -n "$users" ] && [ "$users" -gt 0 ] 2>/dev/null || die "the test restore found no members: this backup is not usable"
  echo "OK: $users members, $projects projects, ${contracts:-0} contracts, $files uploaded files."
  echo "This backup can be restored."
  exit 0
fi

echo "This will REPLACE the current data of the site with the backup $STAMP."
echo "Everything done on the site after that backup will be lost."
read -r -p "Type RESTORE to continue: " answer
[ "$answer" = "RESTORE" ] || die "cancelled"

SAFETY="$BACKUP_DIR/pre-restore_$(date +%Y-%m-%d_%H%M).dump"
if docker compose exec -T db pg_dump -U moucharaka -Fc moucharaka > "$SAFETY" 2>/dev/null && [ -s "$SAFETY" ]; then
  chmod 600 "$SAFETY"
  echo "Current database saved first as $SAFETY"
else
  rm -f "$SAFETY"
  echo "(no current database to save)"
fi

echo "Stopping the site..."
docker compose stop web scheduler >/dev/null 2>&1

echo "Restoring the database..."
docker compose exec -T db pg_restore -U moucharaka -d moucharaka --clean --if-exists --no-owner < "$DB" \
  || echo "(pg_restore reported warnings; checking below)"

echo "Restoring the uploaded files..."
docker compose run --rm -T --no-deps -e SKIP_MIGRATE=1 web tar xzf - -C /data < "$FILES" \
  || die "file restore failed"

echo "Starting the site..."
docker compose up -d >/dev/null 2>&1
for _i in $(seq 1 30); do
  if docker compose exec -T web python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/healthz')" >/dev/null 2>&1; then
    echo "Done: the site is back with the data of $STAMP."
    exit 0
  fi
  sleep 3
done
echo "The site did not answer yet. Check with: docker compose logs web --tail 50"
exit 1
