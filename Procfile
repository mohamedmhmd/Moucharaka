release: python manage.py migrate --noinput
web: gunicorn config.wsgi:application -c deploy/gunicorn.conf.py
