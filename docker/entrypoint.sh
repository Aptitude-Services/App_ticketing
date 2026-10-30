#!/bin/sh
set -e
# Applique les migrations au démarrage, puis lance la commande demandée.
python manage.py migrate --noinput
exec "$@"
