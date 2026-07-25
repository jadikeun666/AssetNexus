"""
Bootstrap broker Dramatiq untuk worker CLI (architecture.md par.4).

MASALAH YANG DIPERBAIKI: dramatiq.get_broker() BAWAAN LIBRARY (bukan kode
project) membuat RedisBroker() POLOS -- tanpa argumen url/host/port apa pun
-- kalau tidak ada broker eksplisit di-set sebelum actor pertama
didefinisikan (lihat dramatiq/broker.py get_broker(), baris ~55-57 versi
1.17.1). RedisBroker() polos itu default ke localhost:6379 tanpa password
-- KEBETULAN cocok dengan Redis dev lokal kita, tapi TIDAK PERNAH membaca
DRAMATIQ_BROKER["OPTIONS"]["url"] di config/settings/base.py sama sekali.
Di produksi (REDIS_URL custom -- host lain, ada password) ini akan diam-
diam salah connect tanpa error yang jelas.

Ditemukan sesi Fase 2 ini saat pertama kali mencoba menjalankan worker
Dramatiq sungguhan untuk app maintenance -- app deterioration/exports di
Fase 0/1 tidak pernah ketahuan karena SEMUA test memanggil actor.fn()
langsung (sinkron, bypass broker sepenuhnya), tidak pernah lewat proses
worker CLI sungguhan.

PERBAIKAN: modul ini diimpor SEBAGAI ARGUMEN PERTAMA CLI dramatiq (posisi
"broker"), sebelum modul actor manapun -- supaya broker Redis yang benar
(dari DRAMATIQ_BROKER setting) sudah ter-set secara global SEBELUM
@dramatiq.actor decorator di apps/{deterioration,exports,maintenance}/jobs.py
dieksekusi (decorator itu memanggil dramatiq.get_broker() pada saat
definisi, bukan pada saat actor dipanggil -- jadi urutan impor ini penting).

Cara pakai (menggantikan `dramatiq apps.maintenance.jobs` yang salah):

    dramatiq config.dramatiq_setup apps.deterioration.jobs apps.exports.jobs apps.maintenance.jobs

TIDAK mengubah apps/deterioration/jobs.py, apps/exports/jobs.py, atau
apps/maintenance/jobs.py sama sekali -- perbaikan murni di titik bootstrap
broker, konsisten dengan batasan sesi ini (tidak menyentuh logic
deterioration yang sudah teruji).
"""
import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")

import django  # noqa: E402

django.setup()

import dramatiq  # noqa: E402
from dramatiq.brokers.redis import RedisBroker  # noqa: E402
from django.conf import settings  # noqa: E402

_redis_broker = RedisBroker(url=settings.DRAMATIQ_BROKER["OPTIONS"]["url"])
dramatiq.set_broker(_redis_broker)
