#!/bin/bash
# Jalankan dengan: source scripts/dev-env.sh
# Membersihkan env var yang bocor dari sesi PredictMaint (proses induk
# window VS Code yang sama) dan mengaktifkan venv assetnexus yang benar.
# Ditemukan berulang kali sesi Fase 4 -- lihat claude.md untuk detail.

unset POSTGRES_DB POSTGRES_USER POSTGRES_PASSWORD POSTGRES_HOST POSTGRES_PORT
unset REDIS_URL REDIS_HOST REDIS_PORT
unset DJANGO_SETTINGS_MODULE DJANGO_SECRET_KEY DJANGO_ALLOWED_HOSTS DEBUG
unset VIRTUAL_ENV VIRTUAL_ENV_PROMPT

deactivate 2>/dev/null
source "$(dirname "${BASH_SOURCE[0]}")/../venv/bin/activate"

echo "python: $(which python)"
echo "sisa env var Postgres/Redis: $(env | grep -iE '^POSTGRES_|^REDIS_' || echo '(bersih)')"
