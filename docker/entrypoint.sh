#!/bin/sh
set -e
# Applique les migrations au démarrage, puis lance la commande demandée.
# Le planificateur (SKIP_MIGRATE=1) laisse le service « web » s'en charger.
if [ "${SKIP_MIGRATE:-0}" != "1" ]; then
  python manage.py migrate --noinput
fi
exec "$@"
