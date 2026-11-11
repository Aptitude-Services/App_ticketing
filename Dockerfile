FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

# LibreOffice (sans interface) et la police du modèle : export du COMEX en PDF.
# INSTALL_LIBREOFFICE=0 : image sans PDF (le PowerPoint reste disponible), utile si le
# serveur ne peut pas télécharger les paquets Debian.
ARG INSTALL_LIBREOFFICE=1
RUN if [ "$INSTALL_LIBREOFFICE" = "1" ]; then \
        apt-get update \
        && apt-get install -y --no-install-recommends libreoffice-impress fonts-montserrat fonts-dejavu-core \
        && rm -rf /var/lib/apt/lists/*; \
    fi

RUN useradd --create-home --uid 1000 app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY --chown=app:app . .
# Certificat de confiance du relais SMTP Postfix : installé s'il est présent dans certs/
# (fichier propre au serveur, hors Git). Sans lui, l'image se construit quand même.
RUN if [ -f certs/postfix-mail.crt ]; then \
        cp certs/postfix-mail.crt /usr/local/share/ca-certificates/postfix-mail.crt \
        && update-ca-certificates; \
    fi
RUN DJANGO_DEBUG=1 python manage.py collectstatic --noinput \
    && mkdir -p /app/media && chown -R app:app /app/media /app/staticfiles \
    && chmod +x /app/docker/entrypoint.sh

USER app
EXPOSE 8000
ENTRYPOINT ["/app/docker/entrypoint.sh"]
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3", "--access-logfile", "-"]
