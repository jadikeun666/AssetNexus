from .base import *  # noqa: F401,F403

DEBUG = True

# CORS -- KHUSUS dev.py, TIDAK PERNAH masuk base.py/production settings.
# Rasionalisasi: di produksi (architecture.md §7), Nginx reverse-proxy
# Django DAN aset statis Angular dari satu origin -- CORS tidak relevan
# sama sekali di sana. Kebutuhan CORS murni artefak `ng serve` (:4200)
# vs `runserver` (:8000) dev lokal yang beda origin.
INSTALLED_APPS += ["corsheaders"]  # noqa: F405

# CorsMiddleware ditaruh SETINGGI MUNGKIN di MIDDLEWARE (rekomendasi resmi
# django-cors-headers), sebelum CommonMiddleware.
MIDDLEWARE = ["corsheaders.middleware.CorsMiddleware"] + MIDDLEWARE  # noqa: F405

CORS_ALLOWED_ORIGINS = [
    "http://localhost:4200",
]

# django-cors-headers default CORS_ALLOW_HEADERS tidak mencakup header
# custom kita (X-Organization-Id, stub org-scoping -- engineering-rules.md
# §8, akan diganti klaim Keycloak asli setelah realm setup). Perlu extend
# daftar default eksplisit, bukan ganti total (supaya header standar
# seperti Content-Type/Authorization tetap diizinkan).
from corsheaders.defaults import default_headers  # noqa: E402

CORS_ALLOW_HEADERS = list(default_headers) + [
    "x-organization-id",
]
