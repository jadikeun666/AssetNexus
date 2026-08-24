"""
Bootstrap Django untuk worker CLI Dramatiq (architecture.md §4).

CATATAN REVISI (Fase 4): broker Dramatiq TIDAK lagi dibuat manual di
sini -- sebelumnya modul ini membuat RedisBroker() SENDIRI setelah
django.setup(), yang menciptakan broker KEDUA dan membuang broker
pertama (dibuat oleh apps/core/apps.py CoreConfig.ready(), yang
terpanggil SELAMA django.setup()) beserta SEMUA actor yang sudah
terdaftar ke situ -- termasuk push_anomaly_alert_job (apps.sensors) dan
semua actor deterioration/exports/maintenance. Bug ini baru terlihat
sesi Fase 4 saat verifikasi WebSocket manual: broker.actors kosong sama
sekali meski modul actor sudah di-import.

apps/core/apps.py CoreConfig.ready() sekarang jadi SATU-SATUNYA titik
broker-setup, terpanggil otomatis lewat django.setup() di bawah ini,
sebelum AppConfig.ready() app manapun yang mendefinisikan @dramatiq.actor
(core didaftarkan PERTAMA di INSTALLED_APPS). Modul ini dipertahankan
(bukan dihapus) karena tetap wajib jadi ARGUMEN PERTAMA CLI dramatiq --
memastikan django.setup() (dan karenanya broker-setup) terjadi sebelum
modul actor manapun di-import oleh Dramatiq CLI:
    dramatiq config.dramatiq_setup apps.deterioration.jobs apps.exports.jobs apps.maintenance.jobs apps.sensors.jobs
"""
import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")

import django  # noqa: E402
django.setup()
