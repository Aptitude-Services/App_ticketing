FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

# LibreOffice (sans interface) et la police du modèle : export du COMEX en PDF.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libreoffice-impress fonts-montserrat fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --uid 1000 app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY --chown=app:app . .
RUN DJANGO_DEBUG=1 python manage.py collectstatic --noinput \
    && mkdir -p /app/media && chown -R app:app /app/media /app/staticfiles \
    && chmod +x /app/docker/entrypoint.sh

USER app
EXPOSE 8000
ENTRYPOINT ["/app/docker/entrypoint.sh"]
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3", "--access-logfile", "-"]
