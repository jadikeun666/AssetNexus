# config/assetnexus.py
# engineering-rules.md §5: single source of truth. Jangan hardcode angka
# di service/job — selalu import dari sini.

DETERIORATION = {
    "MIN_INSPECTIONS_FOR_CTMC": 4,          # formulas.md §2
    "REGIME_COUNT": 3,                       # slow / normal / fast
    "BOOTSTRAP_RESAMPLES": 500,              # formulas.md §3.1
    "CALIBRATION_MAE_THRESHOLD_STATES": 0.5, # formulas.md §6
    "RANDOM_SEED": 42,
    "ANNUAL_INTERVAL_TOLERANCE_YEARS": 1e-2,  # formulas.md §1.4: di bawah
    # toleransi ini, delta_t dianggap "sudah annual" dan jalur
    # eigendecomposition (jax.numpy.linalg.eig) dihindari -- penting
    # karena P bisa defective/near-defective untuk pooled dataset kecil,
    # yang membuat eigendecomposition numerically unstable untuk delta_t
    # yang cuma meleset sedikit dari 1.0 (mis. 365/365.25 hari).
    "CTMC_FIT_LBFGS_MAXITER": 200,            # CTMCLatentFittingService.fit()
    # -- fit UTAMA, presisi penuh dibutuhkan (formulas.md §2.3).
    "BOOTSTRAP_LBFGS_MAXITER": 50,            # formulas.md §3.1 bootstrap --
    # tiap resample cuma perlu MENGUKUR SEBARAN estimasi (bukan titik
    # optimum presisi tinggi seperti fit utama), dan dijalankan 500x via
    # vmap (BootstrapResampler) -- maxiter lebih kecil menjaga total waktu
    # komputasi tetap wajar untuk background job (Dramatiq), TANPA
    # mengurangi jumlah resample (tetap 500, sesuai BOOTSTRAP_RESAMPLES).
    "FUZZY_SANITY_CHECK_EPSILON": 1e-6,        # formulas.md §6: "Must hold
    # exactly" (p_ij^L <= p_ij <= p_ij^U) diinterpretasikan dengan toleransi
    # numerik kecil -- titik estimasi (dari SATU proses fit CTMC) dan batas
    # persentil bootstrap (dari proses optimasi TERPISAH, warm-started dari
    # titik yang sama) bisa berbeda oleh floating point noise murni pada
    # orde 1e-6 meski keduanya representasi valid dari nilai yang sama
    # secara substansi -- konsisten dengan presisi round(...,6) yang sudah
    # dipakai di semua nilai TransitionMatrix.
    "MAX_ANNUAL_RATE": 20.0,                   # formulas.md §2.2: pengaman
    # numerik (BUKAN batas fisik realistis) untuk rate CTMC per tahun.
    # Regime dengan posterior_weight=0 selama fitting TIDAK dikendalikan
    # likelihood sama sekali -- L-BFGS bisa mengembara ke rate ekstrem
    # (ditemukan: ~150.000-660.000/tahun) tanpa gaya penarik kembali.
    # Rate 20/tahun berarti waktu tunggu rata-rata transisi (1/rate) cuma
    # ~18 hari -- absurd secara fisik untuk model deterioration tahunan,
    # jadi ambang ini murni menangkap kasus "tidak dikendalikan data" ini,
    # bukan membatasi hasil fitting sah (yang di semua test kita berkisar
    # 0.1-2). Tanpa clamp ini, Q_r*t di expm(Q_r*t) (CTMCForecastService,
    # formulas.md §2.4) overflow untuk horizon t=2..30 tahun.
}

PINN = {
    "COLLOCATION_POINTS_PER_COMPONENT": 2000,
    "PHYSICS_LOSS_WEIGHT": 1.0,
    "BOUNDARY_LOSS_WEIGHT": 1.0,
    "PHYSICS_RESIDUAL_THRESHOLD": {          # per asset_type
        "bridge": 1e-3,
        "building": 1e-3,
    },
}

OPTIMIZATION = {
    "SOLVER_TIME_LIMIT_SECONDS": 60,         # prd.md §7
    "SOLVER": "CP_SAT",
    "COST_SCALE_TO_CENTS": 100,               # scheduling.md §3.1, §4: CP-SAT
    # cuma menerima koefisien/bound integer -- cost (NUMERIC(14,2), Rupiah)
    # dikonversi ke satuan sen (dikali 100, dibulatkan) sebelum jadi bound
    # budget constraint. Konversi ini LOSSLESS karena NUMERIC(14,2) memang
    # cuma py 2 desimal -- bukan pembulatan yang membuang presisi.
    "OBJECTIVE_COEFFICIENT_SCALE": 10000,      # formulas.md §5.1: koefisien
    # objective (w_b * ΔD_b,t,i) adalah hasil kali importance_weight
    # (NUMERIC(4,2), max 2 desimal) dan probabilitas forecast (JSONField
    # float, presisi jauh lebih halus) -- diskalakan lalu dibulatkan ke
    # integer terdekat agar CP-SAT bisa memaksimalkan objective linear
    # tanpa floating point. Skala 10000 dipilih agar probabilitas sekecil
    # 0.0001 (1 basis poin) masih punya representasi integer != 0.
}

CONDITION_AGGREGATION = {
    "CRITICAL_PENALTY_POINTS": 20,           # asset-registry.md §4
}

DIGITAL_TWIN = {
    "MAX_TRIANGLE_COUNT": 150_000,            # visualization.md §7: mesh di
    # atas ambang ini DITOLAK saat upload dengan error jelas, tidak
    # dibiarkan lolos dan mendegradasi performa viewer secara diam-diam.
    "TIMELINE_DEFAULT_HORIZON_YEARS": 20,      # visualization.md §4: default
    # horizon scrubber kalau tidak ada konteks MaintenancePlan.
    "PLAY_MS_PER_YEAR": 800,                   # visualization.md §4.2:
    # kecepatan animasi "Play" -- 1 tahun per 800ms, warna di-eased
    # (linear interpolation) antar tahun berurutan.
    "INTERVENTION_SNAP_MS": 150,               # visualization.md §4.2:
    # transisi snap-to-green KHUSUS saat playhead melewati tahun
    # intervensi terjadwal -- sengaja TIDAK di-eased (snap), untuk
    # membedakan visual "prediksi model" vs "efek intervensi".
    "CS5_PULSE_EMISSIVE_MIN": 0.1,             # visualization.md §3: pulsing
    "CS5_PULSE_EMISSIVE_MAX": 0.4,             # emissive glow komponen CS5,
    # satu-satunya "flair" animasi selain easing timeline (§7: hanya 2
    # requestAnimationFrame loop kontinu di seluruh viewer).
}
