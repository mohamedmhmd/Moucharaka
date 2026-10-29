#!/bin/sh
set -e
if [ -z "$SKIP_MIGRATE" ]; then
  python manage.py migrate --noinput
fi
exec "$@"
