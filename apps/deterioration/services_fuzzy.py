"""
formulas.md §3 — Fuzzy Markov Bounds (uncertainty layer wrapping CTMC/DTMC).

Secara konsep ini BUKAN model deterioration baru — cuma wrapping
uncertainty di atas fit CTMC yang sudah ada (formulas.md §3.1: "not a
replacement model"). TAPI secara skema disimpan sebagai DeteriorationModel
row TERPISAH, model_type='fuzzy_markov' (database.md §4: fuzzy_lower/upper
hanya terisi untuk model_type ini — lihat diskusi desain 2-model yang
sudah disetujui). Selalu dibuat SETELAH CTMCLatentFittingService.fit()
sukses; parameters menyimpan referensi eksplisit ke model sumbernya
(source_model_id), karena model_version tidak bisa disamakan (constraint
DB: model_version unik per component, lintas model_type).

Constants dipakai dari config.assetnexus.DETERIORATION:
- BOOTSTRAP_RESAMPLES: 500 (formulas.md §3.1)
- RANDOM_SEED: seed tetap (engineering-rules.md §3)

STATUS: CentroidDefuzzificationService.centroid SUDAH DIISI (definisi
numerik centroid disepakati eksplisit dengan product owner, lihat
CONDITION_SCORE_MIDPOINTS di bawah). Method lain (BootstrapResampler,
FuzzyBoundsService) masih skeleton -- badan method NotImplementedError,
diisi di langkah berikutnya.
"""
from __future__ import annotations

from datetime import datetime, timezone

import jax
import jax.numpy as jnp
import jax.scipy.linalg
import jaxopt
import numpy as np

from config.assetnexus import DETERIORATION

from .models import ConditionStateChoices, DegradationForecast, DeteriorationModel, TransitionMatrix
from .services import STATE_INDEX, STATES
from .services_ctmc import (
    N_REGIMES,
    N_RAW_PARAMS_TOTAL,
    N_STATES,
    OFF_DIAGONAL_CELLS,
    REGIME_NAMES,
    CTMCDatasetCollector,
    CTMCLatentFittingService,
    ComponentHistory,
    RegimeForwardFilter,
    batched_joint_log_likelihood,
    pad_histories_to_arrays,
)

# asset-registry.md §3.1: titik tengah range condition_score per state.
# Dipakai SEBAGAI BOBOT NUMERIK untuk centroid defuzzification (formulas.md
# §3.2) -- bukan variabel baru, murni derivatif dari skema yang sudah
# fixed. Disepakati eksplisit dengan product owner sebelum diimplementasi
# (formulas.md §3.2 sendiri tidak merincikan definisi numerik "centroid").
CONDITION_SCORE_MIDPOINTS = {
    ConditionStateChoices.CS1.value: 95.0,   # range 90-100
    ConditionStateChoices.CS2.value: 79.5,   # range 70-89
    ConditionStateChoices.CS3.value: 59.5,   # range 50-69
    ConditionStateChoices.CS4.value: 37.0,   # range 25-49
    ConditionStateChoices.CS5.value: 12.0,   # range 0-24
}


class BootstrapResampler:
    """formulas.md §3.1: bootstrap resampling (500 resample, fixed seed —
    engineering-rules.md §3) atas dataset pooled yang SAMA dipakai
    CTMCLatentFittingService (CTMCDatasetCollector.collect), untuk dapat
    distribusi empiris tiap q_ij lewat refitting berulang.

    Implementasi FASE C (vmap+padding) + WARM-START (revisi disepakati
    product owner setelah pengukuran performa CPU-only menunjukkan titik
    awal acak terlalu lambat konvergen): SETIAP resample di-refit via
    jaxopt.LBFGS, SEMUA n_resamples dijalankan SEKALIGUS lewat jax.vmap
    (arsitektur Fase C TIDAK dibongkar -- diverifikasi identik dengan
    pemanggilan sekuensial sebelumnya). init_params SEKARANG bisa diisi
    dari hasil fit CTMC ASLI (fitted_params_from_original_fit) alih-alih
    titik acak seragam -- karena data bootstrap adalah perturbasi kecil
    dari data asli, warm-start membuat L-BFGS konvergen jauh lebih cepat
    pada maxiter yang SAMA (BOOTSTRAP_LBFGS_MAXITER), TANPA menambah
    risiko konvergensi prematur seperti sekadar menurunkan maxiter tanpa
    warm-start. TETAP 500 resample penuh sesuai formulas.md §3.1, tidak
    ada penyederhanaan jumlah resample maupun rumus."""

    def __init__(self, fitting_service: CTMCLatentFittingService | None = None):
        self.fitting_service = fitting_service or CTMCLatentFittingService()

    def _fit_one_resample(self, cs_batch, dt_batch, mask_batch, init_params):
        """Satu evaluasi fit CTMC penuh (joint MLE) atas SATU dataset
        resample (yang sendiri berisi banyak histori komponen, sudah
        di-pad). Dipanggil lewat jax.vmap di resample_and_refit -- BUKAN
        dipanggil langsung dalam loop Python untuk 500 resample."""
        fitting_service = self.fitting_service

        def objective(raw_params):
            cs_generators, regime_generator, regime_priors = fitting_service._unpack_params(raw_params)
            forward_filter = RegimeForwardFilter()
            Q_joint = forward_filter.build_joint_generator(cs_generators, regime_generator)
            return batched_joint_log_likelihood(
                Q_joint, cs_batch, dt_batch, mask_batch, regime_priors, N_REGIMES
            )

        solver = jaxopt.LBFGS(
            fun=objective, maxiter=DETERIORATION["BOOTSTRAP_LBFGS_MAXITER"], tol=1e-6
        )
        result = solver.run(init_params)
        return result.params

    def resample_and_refit(
        self,
        histories: list[ComponentHistory],
        seed: int,
        n_resamples: int,
        target_component_history: ComponentHistory | None = None,
        init_params_override: jnp.ndarray | None = None,
    ) -> list[dict]:
        """Return list of dict, satu per resample, berisi:
        {"cs_generators": {regime_index: Q_r}, "regime_generator": ...,
        "regime_priors": ..., "posterior": {regime_index: p} atau None}.

        REVISI (Opsi A, disepakati product owner): SEKARANG mengembalikan
        regime_generator & regime_priors per resample (bukan cuma
        cs_generators) -- diperlukan FuzzyBoundsService untuk menghitung
        posterior regime KHUSUS komponen target SETIAP resample (bukan
        memakai posterior tunggal dari ctmc_model asli untuk semua
        resample), sesuai formulas.md §2.4 (posterior adalah bagian
        integral forecast, bukan konstanta).

        target_component_history: kalau diberikan, posterior regime
        komponen ini dihitung ULANG untuk SETIAP resample (via
        RegimeForwardFilter.posterior_regime_probabilities, method yang
        sudah teruji, TIDAK dimodifikasi). Kalau None, field "posterior"
        di tiap hasil bernilai None (dipakai test struktural yang tidak
        butuh posterior).

        init_params_override: kalau diberikan, dipakai sebagai titik awal
        SEMUA resample (warm-start dari hasil CTMCLatentFittingService.fit()
        asli -- lihat FuzzyBoundsService.fit()). Kalau None (default),
        fallback ke titik acak seragam dari seed."""
        n_components = len(histories)
        if n_components == 0:
            raise ValueError("Tidak ada histori untuk bootstrap resampling.")

        cs_indices_batch, delta_years_batch, mask_batch = pad_histories_to_arrays(histories)

        # Resample INDEKS komponen (dengan pengembalian), seed tetap
        # (engineering-rules.md §3 -- reproducibility).
        keys = jax.random.split(jax.random.PRNGKey(seed), n_resamples)
        resample_indices = jnp.stack([
            jax.random.choice(k, n_components, shape=(n_components,), replace=True) for k in keys
        ])

        resampled_cs = cs_indices_batch[resample_indices]
        resampled_dt = delta_years_batch[resample_indices]
        resampled_mask = mask_batch[resample_indices]

        if init_params_override is not None:
            init_params = init_params_override
        else:
            init_params = 0.1 * jax.random.normal(jax.random.PRNGKey(seed), shape=(N_RAW_PARAMS_TOTAL,))

        vmapped_fit = jax.vmap(self._fit_one_resample, in_axes=(0, 0, 0, None))
        fitted_params_batch = vmapped_fit(resampled_cs, resampled_dt, resampled_mask, init_params)

        forward_filter = RegimeForwardFilter()
        results = []
        for idx in range(n_resamples):
            cs_generators, regime_generator, regime_priors = self.fitting_service._unpack_params(
                fitted_params_batch[idx]
            )

            posterior_dict = None
            if target_component_history is not None:
                posterior = forward_filter.posterior_regime_probabilities(
                    target_component_history, cs_generators, regime_generator, regime_priors,
                )
                posterior_dict = {r: float(posterior[r]) for r in range(N_REGIMES)}

            results.append({
                "cs_generators": {r: cs_generators[r] for r in range(N_REGIMES)},
                "regime_generator": regime_generator,
                "regime_priors": regime_priors,
                "posterior": posterior_dict,
            })

        return results


class CentroidDefuzzificationService:
    """formulas.md §3.2: confidence_width(t) = centroid(π̃_upper(t)) -
    centroid(π̃_lower(t)).

    Definisi numerik "centroid": expected value dari state_probabilities,
    berbobot CONDITION_SCORE_MIDPOINTS (asset-registry.md §3.1) -- disepakati
    eksplisit dengan product owner sebelum diimplementasikan (formulas.md
    §3.2 sendiri tidak merincikan definisi numerik ini)."""

    def centroid(self, state_probabilities: dict) -> float:
        """formulas.md §3.2: expected value dari distribusi state_probabilities,
        berbobot condition_score midpoint per state (asset-registry.md §3.1),
        disepakati eksplisit dengan product owner (lihat CONDITION_SCORE_MIDPOINTS
        module-level di atas). Hasilnya berada di skala 0-100 yang sama dengan
        condition_score -- BUKAN dikembalikan ke model sebagai input
        (engineering-rules.md §4: condition_score display-only, never fed
        back as model input; di sini cuma dipakai untuk menghitung lebar
        confidence_width yang ditampilkan di 2D chart, formulas.md §3.2)."""
        return sum(
            float(prob) * CONDITION_SCORE_MIDPOINTS[state]
            for state, prob in state_probabilities.items()
        )


class FuzzyBoundsService:
    """architecture.md §3. Dipanggil dari jobs.py setelah
    CTMCLatentFittingService.fit() sukses, untuk component yang sama."""

    def __init__(
        self,
        bootstrap_resampler: BootstrapResampler | None = None,
        centroid_service: CentroidDefuzzificationService | None = None,
    ):
        self.bootstrap_resampler = bootstrap_resampler or BootstrapResampler()
        self.centroid_service = centroid_service or CentroidDefuzzificationService()

    def fit(self, ctmc_model: DeteriorationModel, histories: list[ComponentHistory]) -> DeteriorationModel:
        """Return DeteriorationModel baru, model_type=FUZZY_MARKOV.
        parameters = {"source_model_id": str(ctmc_model.id), "seed": ...}.
        TransitionMatrix row: rate_or_probability = titik estimasi (sama
        dengan ctmc_model), fuzzy_lower/upper = persentil 95% CI (2.5/97.5,
        disepakati product owner) dari BootstrapResampler. model_version:
        global per component (fix Langkah sebelumnya di services.py,
        dipakai sama di sini).

        formulas.md §6: fuzzy sanity check (p_ij^L <= p_ij <= p_ij^U) HARUS
        berlaku -- kalau gagal, model TIDAK disimpan (fit job gagal keras),
        bukan disimpan dalam state invalid."""
        params = ctmc_model.parameters
        cs_generators_original = [
            jnp.asarray(params["generators"][regime_name]) for regime_name in REGIME_NAMES
        ]
        regime_generator_original = jnp.asarray(params["regime_generator"])
        regime_priors_original = jnp.asarray(params["regime_priors"])
        posterior_original = {
            r: params["regime_posterior_this_component"][REGIME_NAMES[r]] for r in range(N_REGIMES)
        }

        # WARM-START: pack parameter hasil fit CTMC ASLI jadi raw_params,
        # dipakai sebagai titik awal SEMUA 500 resample (disepakati product
        # owner setelah pengukuran performa -- lihat komentar BootstrapResampler).
        fitting_service = CTMCLatentFittingService()
        init_params_override = fitting_service._pack_params(
            cs_generators_original, regime_generator_original, regime_priors_original
        )

        component = ctmc_model.component
        target_history = next(
            (h for h in histories if str(h.component_id) == str(component.id)), None
        )
        if target_history is None:
            raise ValueError(
                f"Component {component.id} tidak ditemukan di histories yang diberikan "
                f"untuk fuzzy bounds fitting."
            )

        seed = DETERIORATION["RANDOM_SEED"]
        n_resamples = DETERIORATION["BOOTSTRAP_RESAMPLES"]  # 500, formulas.md §3.1 -- TIDAK dikurangi

        bootstrap_results = self.bootstrap_resampler.resample_and_refit(
            histories,
            seed=seed,
            n_resamples=n_resamples,
            target_component_history=target_history,
            init_params_override=init_params_override,
        )

        # Untuk SETIAP resample: Q_bar = marginalisasi posterior REGIME
        # KHUSUS resample itu (Opsi A, disepakati product owner) -- BUKAN
        # posterior tunggal dari ctmc_model asli dipakai untuk semua resample.
        Q_bar_per_resample = []
        for result in bootstrap_results:
            cs_generators_r = result["cs_generators"]
            posterior_r = result["posterior"]
            Q_bar_r = sum(posterior_r[r] * np.asarray(cs_generators_r[r]) for r in range(N_REGIMES))
            Q_bar_per_resample.append(Q_bar_r)

        Q_bar_stack = np.stack(Q_bar_per_resample, axis=0)  # (n_resamples, N_STATES, N_STATES)

        # Titik estimasi (SAMA dengan yang tersimpan di ctmc_model.TransitionMatrix) --
        # dihitung ulang dari parameters tersimpan untuk konsistensi, bukan
        # query database terpisah.
        Q_bar_point_estimate = sum(
            posterior_original[r] * np.asarray(cs_generators_original[r]) for r in range(N_REGIMES)
        )

        fuzzy_lower_by_cell = {}
        fuzzy_upper_by_cell = {}
        for i, j in OFF_DIAGONAL_CELLS:
            cell_samples = Q_bar_stack[:, i, j]
            lower = float(np.percentile(cell_samples, 2.5))
            upper = float(np.percentile(cell_samples, 97.5))
            point = float(Q_bar_point_estimate[i, j])

            # formulas.md §6: fuzzy sanity check -- HARUS berlaku, kalau
            # tidak, fit job gagal keras (model TIDAK disimpan). Epsilon
            # toleransi (bukan pelonggaran formula, murni floating point
            # noise dari dua proses optimasi terpisah -- lihat komentar
            # FUZZY_SANITY_CHECK_EPSILON di config/assetnexus.py) diterapkan
            # HANYA pada PERBANDINGAN, nilai fuzzy_lower/fuzzy_upper yang
            # disimpan TETAP persis hasil persentil asli, tidak diubah.
            epsilon = DETERIORATION["FUZZY_SANITY_CHECK_EPSILON"]
            if not (lower - epsilon <= point <= upper + epsilon):
                raise ValueError(
                    f"Fuzzy sanity check gagal untuk cell ({STATES[i]}->{STATES[j]}): "
                    f"lower={lower:.6f}, point={point:.6f}, upper={upper:.6f} -- "
                    f"p_ij^L <= p_ij <= p_ij^U TIDAK terpenuhi bahkan dengan toleransi "
                    f"{epsilon} (formulas.md §6). Model TIDAK disimpan."
                )

            fuzzy_lower_by_cell[(i, j)] = lower
            fuzzy_upper_by_cell[(i, j)] = upper

        last_version = (
            DeteriorationModel.objects.filter(component=component)
            .order_by("-model_version")
            .values_list("model_version", flat=True)
            .first()
        ) or 0

        model = DeteriorationModel.objects.create(
            component=component,
            model_type=DeteriorationModel.ModelType.FUZZY_MARKOV,
            parameters={
                "source_model_id": str(ctmc_model.id),
                "seed": seed,
                "n_resamples": n_resamples,
                "percentiles": [2.5, 97.5],
            },
            fitted_at=datetime.now(timezone.utc),
            model_version=last_version + 1,
            training_data_hash=ctmc_model.training_data_hash,
        )

        transition_rows = [
            TransitionMatrix(
                model=model,
                from_state=STATES[i],
                to_state=STATES[j],
                rate_or_probability=round(float(Q_bar_point_estimate[i, j]), 6),
                fuzzy_lower=round(fuzzy_lower_by_cell[(i, j)], 6),
                fuzzy_upper=round(fuzzy_upper_by_cell[(i, j)], 6),
            )
            for i, j in OFF_DIAGONAL_CELLS
        ]
        TransitionMatrix.objects.bulk_create(transition_rows)

        return model

    def _build_bounding_generator(self, fuzzy_model: DeteriorationModel, use_upper: bool) -> np.ndarray:
        """Susun Q_bar_upper atau Q_bar_lower (N_STATES x N_STATES) dari
        TransitionMatrix.fuzzy_lower/fuzzy_upper milik fuzzy_model --
        SATU generator gabungan (disepakati product owner), bukan per-regime
        terpisah, konsisten dengan bagaimana Q_bar sudah diperlakukan
        sebagai representasi tunggal di TransitionMatrix."""
        rows = TransitionMatrix.objects.filter(model=fuzzy_model)
        Q = np.zeros((N_STATES, N_STATES))
        for row in rows:
            i = STATE_INDEX[row.from_state]
            j = STATE_INDEX[row.to_state]
            value = row.fuzzy_upper if use_upper else row.fuzzy_lower
            Q[i, j] = float(value)

        row_sums = Q.sum(axis=1)
        Q = Q - np.diag(row_sums)  # diagonal diturunkan, sama seperti Q_bar biasa
        return Q

    def annotate_forecast_confidence_width(
        self,
        forecast: DegradationForecast,
        fuzzy_model: DeteriorationModel,
        current_state: str,
    ) -> DegradationForecast:
        """formulas.md §3.2: propagate π̃_upper/π̃_lower lewat rumus forecast
        YANG SAMA dengan CTMCForecastService.generate (§2.4: π(0)·expm(Q·t)),
        lalu ambil selisih centroid. MENGISI confidence_width yang sudah ada
        di forecast (NULL sejak Fase 0) -- tidak membuat row DegradationForecast
        baru.

        current_state: state AWAL yang dipakai saat forecast ini pertama
        dibuat (CTMCForecastService.generate) -- DegradationForecast TIDAK
        menyimpan field ini (database.md §4 tidak merincikannya), jadi
        diteruskan eksplisit oleh pemanggil yang tahu current_state
        tersebut (jobs.py, dipanggil dalam alur yang sama)."""
        Q_bar_upper = self._build_bounding_generator(fuzzy_model, use_upper=True)
        Q_bar_lower = self._build_bounding_generator(fuzzy_model, use_upper=False)

        pi_0 = np.zeros(N_STATES)
        pi_0[STATE_INDEX[current_state]] = 1.0

        t = forecast.forecast_year - datetime.now(timezone.utc).year

        P_upper_t = np.asarray(jax.scipy.linalg.expm(Q_bar_upper * t))
        P_lower_t = np.asarray(jax.scipy.linalg.expm(Q_bar_lower * t))

        pi_upper_t = pi_0 @ P_upper_t
        pi_lower_t = pi_0 @ P_lower_t

        pi_upper_t = np.clip(pi_upper_t, 0.0, None)
        pi_upper_t = pi_upper_t / pi_upper_t.sum()
        pi_lower_t = np.clip(pi_lower_t, 0.0, None)
        pi_lower_t = pi_lower_t / pi_lower_t.sum()

        state_probs_upper = {STATES[i]: float(pi_upper_t[i]) for i in range(N_STATES)}
        state_probs_lower = {STATES[i]: float(pi_lower_t[i]) for i in range(N_STATES)}

        centroid_upper = self.centroid_service.centroid(state_probs_upper)
        centroid_lower = self.centroid_service.centroid(state_probs_lower)

        confidence_width = round(abs(centroid_upper - centroid_lower), 3)

        # HINDARI forecast.save(update_fields=[...]) -- objek hasil
        # bulk_create() (dipakai CTMCForecastService.generate) punya
        # _state.adding=True meski pk sudah terisi (kuirk Django), yang
        # membuat save(update_fields=...) gagal dengan "did not affect
        # any rows" walau row-nya benar-benar ada di database. .update()
        # di level queryset bekerja langsung via pk, tidak bergantung pada
        # state Python in-memory objek sama sekali -- aman untuk objek
        # dari bulk_create maupun objek yang di-fetch normal.
        DegradationForecast.objects.filter(pk=forecast.pk).update(
            confidence_width=confidence_width
        )
        forecast.confidence_width = confidence_width  # sinkronkan objek in-memory
        return forecast
