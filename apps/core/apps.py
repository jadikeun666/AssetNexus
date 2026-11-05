from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.core"
    label = "core"

    def ready(self):
        """
        Set broker Dramatiq yang benar di SINI -- apps.core adalah app
        PERTAMA di INSTALLED_APPS (config/settings/base.py), jadi
        ready() ini terpanggil sebelum AppConfig.ready() app manapun
        yang mendefinisikan @dramatiq.actor (sensors, deterioration,
        exports, maintenance).

        BUG YANG DIPERBAIKI (ditemukan sesi Fase 4, verifikasi WebSocket
        manual): dramatiq.get_broker() BAWAAN LIBRARY membuat
        RedisBroker() POLOS -- localhost:6379, TIDAK PERNAH baca
        DRAMATIQ_BROKER settings -- kalau belum ada broker eksplisit
        di-set SEBELUM actor pertama didefinisikan. Ini terjadi di
        SETIAP proses yang memanggil django.setup() TANPA lebih dulu
        lewat config/dramatiq_setup.py: python manage.py runserver,
        pytest (via pytest-django), DAN uvicorn config.asgi:application
        (config/asgi.py, sebelum patch ini) -- port 6379 BUKAN kosong,
        itu Redis project predictmaint yang berjalan paralel, jadi job
        terkirim ke Redis SALAH tanpa error apa pun.

        config/dramatiq_setup.py (Fase 2) memperbaiki ini KHUSUS untuk
        proses worker CLI (diimpor sebagai argumen pertama sebelum modul
        actor). ready() di sini memperbaikinya secara GLOBAL untuk semua
        proses yang memanggil django.setup() -- termasuk dramatiq_setup.py
        sendiri (import ulang broker yang sama, idempotent, tidak
        berbahaya dijalankan dua kali).
        """
        import dramatiq
        from django.conf import settings
        from django.utils.module_loading import import_string

        # Kelas broker dibaca dari settings.DRAMATIQ_BROKER["BROKER"] (sebelumnya
        # kunci ini diabaikan dan RedisBroker di-hardcode) supaya config/settings/
        # test.py bisa memakai StubBroker: test TIDAK boleh mengirim pesan ke Redis
        # dev -- pesan itu diambil worker dev dan gagal DoesNotExist karena ID-nya
        # milik database test. Dev/prod tetap RedisBroker, perilaku tidak berubah.
        broker_cfg = settings.DRAMATIQ_BROKER
        broker_class = import_string(broker_cfg["BROKER"])
        dramatiq.set_broker(broker_class(**broker_cfg.get("OPTIONS", {})))
