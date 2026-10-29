FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    MEDIA_ROOT=/data/media PRIVATE_MEDIA_ROOT=/data/private_media

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
# Translations: locale/ar/LC_MESSAGES/django.mo is committed (rebuild with scripts/i18n.py compile)
RUN SECRET_KEY=build DEBUG=False python manage.py collectstatic --noinput \
    && useradd --create-home app && mkdir -p /data/media /data/private_media && chown -R app /data /app
USER app
EXPOSE 8000
ENTRYPOINT ["sh", "deploy/entrypoint.sh"]
CMD ["gunicorn", "config.wsgi:application", "-c", "deploy/gunicorn.conf.py"]
