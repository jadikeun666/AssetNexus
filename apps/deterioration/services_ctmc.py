"""
formulas.md §2 — CTMC dengan Latent Aging Regime.

Dipanggil dari jobs.py saat inspection_count >= config.assetnexus
.DETERIORATION["MIN_INSPECTIONS_FOR_CTMC"]. Melengkapi, BUKAN mengganti,
DiscreteMarkovFittingService/ForecastService di services.py — baseline
DTMC tetap dipakai untuk component yang belum capai ambang ini
(prd.md §9: "graceful degradation").

Constants dipakai dari config.assetnexus.DETERIORATION:
- REGIME_COUNT: jumlah latent regime (slow/normal/fast), formulas.md §2.1
- RANDOM_SEED: seed tetap untuk init parameter L-BFGS (engineering-rules.md §3)

STATUS: skeleton — struktur class & method signature untuk direview,
badan method sengaja NotImplementedError, diisi di langkah berikutnya.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone

import jax
import jax.numpy as jnp
import numpy as np

import jax.scipy.linalg
import jaxopt

from apps.inspections.models import InspectionRecord

from config.assetnexus import DETERIORATION

from .models import DegradationForecast, DeteriorationModel, TransitionMatrix
from .services import STATE_INDEX, STATES

N_STATES = 5  # CS1..CS5, formulas.md §2.2

# formulas.md §1.1/§2.2: hanya sel (i,j) dengan j > i yang punya rate bebas
# (monotone deterioration-only, sama seperti DTMC). Urutan tetap & deterministik
# supaya raw_params index <-> (i,j) tidak pernah ambigu antar pemanggilan.
OFF_DIAGONAL_CELLS = [(i, j) for i in range(N_STATES) for j in range(N_STATES) if j > i]
N_RAW_PARAMS_PER_REGIME = len(OFF_DIAGONAL_CELLS)  # 4+3+2+1+0 = 10

REGIME_NAMES = ["slow", "normal", "fast"]  # formulas.md §2.1, urutan tetap = index 0/1/2
N_REGIMES = len(REGIME_NAMES)
assert DETERIORATION["REGIME_COUNT"] == N_REGIMES, (
    "config/assetnexus.py DETERIORATION['REGIME_COUNT'] harus konsisten dengan REGIME_NAMES"
)

# formulas.md §2.3: "regime-transition rates" -- regime SEARAH (disepakati
# product owner). Filosofi SAMA dengan OFF_DIAGONAL_CELLS untuk CS: semua
# pasangan r2>r1 diizinkan (bukan cuma tetangga slow->normal->fast), demi
# konsistensi desain -- dokumen tidak merinci topologi transisi regime,
# jadi ini keputusan desain eksplisit, bukan penyimpangan dari formulas.md.
REGIME_OFF_DIAGONAL_CELLS = [(i, j) for i in range(N_REGIMES) for j in range(N_REGIMES) if j > i]
N_RAW_PARAMS_REGIME_GENERATOR = len(REGIME_OFF_DIAGONAL_CELLS)  # 3

# Layout raw_params GABUNGAN untuk satu fitting run penuh
# (CTMCLatentFittingService._unpack_params):
#   [0 : N_REGIMES*N_RAW_PARAMS_PER_REGIME)                    -> Q_r per regime
#   [... : ...+N_RAW_PARAMS_REGIME_GENERATOR)                   -> regime_generator (searah)
#   [... : ...+N_REGIMES)                                        -> regime_priors (softmax)
N_RAW_PARAMS_TOTAL = (
    N_REGIMES * N_RAW_PARAMS_PER_REGIME + N_RAW_PARAMS_REGIME_GENERATOR + N_REGIMES
)


class ComponentHistory:
    """Value object: satu histori komponen (urutan observasi condition_state
    berurutan waktu). Beda dari `_collect_transition_pairs` milik DTMC di
    services.py, yang memotong histori jadi pasangan (from,to) saja — di sini
    kita butuh SELURUH urutan per komponen utuh, karena forward-filtering
    regime (§2.1) butuh histori lengkap, bukan pasangan transisi terpotong."""

    def __init__(self, component_id, observations: list[tuple[str, "datetime"]]):
        self.component_id = component_id
        self.observations = observations  # [(condition_state, inspected_at), ...] terurut waktu


class CTMCDatasetCollector:
    """formulas.md §2.3: fitting joint MLE dilakukan "over the full pooled +
    clustered dataset described in §1.3" — pooling SAMA seperti DTMC (per
    asset_type + component_type, never across whole portfolio)."""

    def collect(self, organization_id, asset_type: str, component_type: str) -> list[ComponentHistory]:
        """Return histori LENGKAP tiap komponen dalam cluster (asset_type,
        component_type) — bukan pasangan transisi terpotong seperti DTMC.
        Pooling identik dengan DiscreteMarkovFittingService._collect_transition_pairs
        di services.py (formulas.md §1.3 / §2.3: cluster sama, never across
        whole portfolio), tapi tidak dipotong jadi pasangan -- urutan penuh
        per komponen dipertahankan untuk forward-filtering (§2.1)."""
        records = list(
            InspectionRecord.objects.for_organization(organization_id)
            .filter(
                component__asset__asset_type=asset_type,
                component__component_type=component_type,
                condition_state__isnull=False,
            )
            .order_by("component_id", "inspected_at")
            .values("component_id", "inspected_at", "condition_state")
        )

        by_component: dict = {}
        for r in records:
            by_component.setdefault(r["component_id"], []).append(r)

        histories = []
        for component_id, component_records in by_component.items():
            observations = [(r["condition_state"], r["inspected_at"]) for r in component_records]
            histories.append(ComponentHistory(component_id=component_id, observations=observations))

        return histories

    def hash_training_data(self, histories: list[ComponentHistory]) -> str:
        """Prinsip sama dengan DiscreteMarkovFittingService._hash_training_data
        (engineering-rules.md §3) — SHA-256 atas seluruh data pooled yang
        dipakai fitting, bukan cuma histori satu komponen. Diurutkan
        deterministik by component_id supaya hash tidak bergantung pada
        urutan dict Python (yang tidak dijamin stabil lintas proses)."""
        parts = []
        for history in sorted(histories, key=lambda h: str(h.component_id)):
            for condition_state, inspected_at in history.observations:
                parts.append(f"{history.component_id}:{inspected_at.isoformat()}:{condition_state}")
        payload = "|".join(parts)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class GeneratorMatrixParameterization:
    """formulas.md §2.2: Q_r harus tetap generator matrix VALID (off-diagonal
    >= 0, baris jumlah 0, struktur monoton j>=i saja) di SETIAP iterasi
    optimasi gradient — tapi jaxopt.LBFGS itu unconstrained. Kelas ini
    menjembatani lewat reparameterisasi (softplus pada off-diagonal rate
    mentah, diagonal diturunkan agar baris berjumlah nol) — Q_r hasil akhir
    tetap generator matrix valid persis §2.2, cuma RUANG PENCARIAN optimizer
    yang tak terbatas. Dipisah jadi class sendiri supaya bisa direview dan
    diuji terpisah dari logic fitting itu sendiri."""

    def unconstrained_to_generator(self, raw_params: jnp.ndarray) -> jnp.ndarray:
        """raw_params (panjang N_RAW_PARAMS_PER_REGIME=10) -> Q_r (5x5) valid
        generator matrix (formulas.md §2.2):
          - off-diagonal j>i: softplus(raw_params) >= 0 selalu, apa pun nilai
            raw_params -- ini yang membuat Q_r valid di SETIAP titik optimasi,
            bukan cuma di titik optimal akhir.
          - off-diagonal j<i: 0 (monotone deterioration-only, formulas.md §1.1,
            berlaku sama untuk CTMC per §2.1 "within a regime, transitions
            follow §1's monotone degradation structure").
          - diagonal Q_r[i][i]: DITURUNKAN, bukan parameter bebas, sebagai
            -Σ_{j!=i} Q_r[i][j], supaya baris berjumlah nol persis (syarat
            generator matrix §2.2). Untuk CS5 (absorbing, i=4): tidak ada
            off-diagonal j>i, jadi otomatis Q_r[4][4]=0 -- absorbing state
            konsisten formulas.md §2.1.
        """
        assert raw_params.shape == (N_RAW_PARAMS_PER_REGIME,), (
            f"Expected {N_RAW_PARAMS_PER_REGIME} raw params, got {raw_params.shape}"
        )
        rates = jax.nn.softplus(raw_params)  # selalu >= 0
        # Pengaman numerik (config/assetnexus.py MAX_ANNUAL_RATE): regime
        # dengan posterior_weight=0 selama fitting tidak dikendalikan
        # likelihood -- L-BFGS bisa mengembara ke rate ekstrem, yang
        # overflow saat expm(Q_r*t) dihitung untuk horizon multi-tahun
        # (formulas.md §2.4). Clip di SINI (bukan cuma di titik konsumsi)
        # supaya SEMUA konsumen (forecast, bootstrap, dst) otomatis aman.
        rates = jnp.clip(rates, None, DETERIORATION["MAX_ANNUAL_RATE"])

        Q = jnp.zeros((N_STATES, N_STATES))
        for idx, (i, j) in enumerate(OFF_DIAGONAL_CELLS):
            Q = Q.at[i, j].set(rates[idx])

        row_sums_off_diag = Q.sum(axis=1)
        Q = Q - jnp.diag(row_sums_off_diag)  # diagonal = -Σ off-diagonal, baris jadi 0

        return Q

    def generator_to_unconstrained_init(self, seed: int) -> jnp.ndarray:
        """Titik awal optimasi, deterministik dari seed (engineering-rules.md
        §3 — reproducibility: re-fit data+seed sama harus bit-identical).
        Init di sekitar 0 (bukan besar) -- softplus(0)=log(2)~0.69, rate awal
        yang masuk akal (bukan nol persis, supaya gradient tidak mati di awal;
        bukan juga sangat besar, supaya tidak overshoot)."""
        key = jax.random.PRNGKey(seed)
        return 0.1 * jax.random.normal(key, shape=(N_RAW_PARAMS_PER_REGIME,))

    def generator_to_unconstrained(self, Q: jnp.ndarray) -> jnp.ndarray:
        """INVERSE dari unconstrained_to_generator -- dipakai untuk WARM-START
        BootstrapResampler (formulas.md §3.1) dari hasil CTMCLatentFittingService
        .fit() yang tersimpan sebagai Q_r matriks jadi (bukan raw_params mentah).
        softplus(x)=log(1+e^x) -> inverse: x=log(e^y-1)=log(expm1(y)). y=0 exact
        (rate nol persis) di-clip ke epsilon kecil sebelum log -- softplus hanya
        MENDEKATI 0 saat x->-inf, tidak ada preimage eksak untuk y=0 persis;
        clipping menghasilkan x sangat negatif, konsisten dengan limit tsb.

        PENGAMANAN OVERFLOW (ditemukan lewat debugging NaN di FuzzyBoundsService):
        untuk rate BESAR (regime dengan posterior_weight=0 selama fitting bisa
        melenceng bebas ke ratusan ribu, tidak dikontrol data sama sekali),
        expm1(rate) overflow -> log(inf)=inf -> merambat jadi NaN begitu
        dikalikan bobot posterior nol di pemanggil (0*inf=nan). softplus(x)~=x
        untuk x besar (limit matematis log(1+e^x)->x), jadi di atas THRESHOLD,
        rate dikembalikan LANGSUNG sebagai raw_params (aproksimasi valid,
        galat dapat diabaikan), TANPA PERNAH mengevaluasi expm1 pada nilai
        yang bisa overflow (input di-clip SEBELUM dipakai di kedua cabang)."""
        LARGE_RATE_THRESHOLD = 20.0  # softplus(20) ~= 20, galat dapat diabaikan
        rates = jnp.array([Q[i, j] for i, j in OFF_DIAGONAL_CELLS])
        rates_safe_for_expm1 = jnp.clip(rates, 1e-10, LARGE_RATE_THRESHOLD)
        small_rate_branch = jnp.log(jnp.expm1(rates_safe_for_expm1))
        return jnp.where(rates > LARGE_RATE_THRESHOLD, rates, small_rate_branch)


class RegimeGeneratorParameterization:
    """formulas.md §2.3 ("regime-transition rates"): generator regime
    (N_REGIMES x N_REGIMES) direparameterisasi PERSIS filosofi yang sama
    dengan GeneratorMatrixParameterization (softplus off-diagonal, diagonal
    diturunkan) -- class TERPISAH (bukan reuse langsung) karena ukurannya
    beda (N_REGIMES, bukan N_STATES) dan supaya GeneratorMatrixParameterization
    yang sudah teruji tidak disentuh."""

    def unconstrained_to_generator(self, raw_params: jnp.ndarray) -> jnp.ndarray:
        assert raw_params.shape == (N_RAW_PARAMS_REGIME_GENERATOR,), (
            f"Expected {N_RAW_PARAMS_REGIME_GENERATOR} raw params, got {raw_params.shape}"
        )
        rates = jax.nn.softplus(raw_params)
        # Pengaman numerik yang sama dengan GeneratorMatrixParameterization
        # -- lihat komentar MAX_ANNUAL_RATE di config/assetnexus.py.
        rates = jnp.clip(rates, None, DETERIORATION["MAX_ANNUAL_RATE"])

        Q = jnp.zeros((N_REGIMES, N_REGIMES))
        for idx, (i, j) in enumerate(REGIME_OFF_DIAGONAL_CELLS):
            Q = Q.at[i, j].set(rates[idx])

        row_sums_off_diag = Q.sum(axis=1)
        Q = Q - jnp.diag(row_sums_off_diag)
        return Q

    def generator_to_unconstrained(self, Q: jnp.ndarray) -> jnp.ndarray:
        """INVERSE dari unconstrained_to_generator -- prinsip SAMA persis
        dengan GeneratorMatrixParameterization.generator_to_unconstrained
        (termasuk pengamanan overflow untuk rate besar via LARGE_RATE_THRESHOLD),
        cuma memakai REGIME_OFF_DIAGONAL_CELLS (bukan OFF_DIAGONAL_CELLS)
        karena ukurannya beda (N_REGIMES, bukan N_STATES)."""
        LARGE_RATE_THRESHOLD = 20.0
        rates = jnp.array([Q[i, j] for i, j in REGIME_OFF_DIAGONAL_CELLS])
        rates_safe_for_expm1 = jnp.clip(rates, 1e-10, LARGE_RATE_THRESHOLD)
        small_rate_branch = jnp.log(jnp.expm1(rates_safe_for_expm1))
        return jnp.where(rates > LARGE_RATE_THRESHOLD, rates, small_rate_branch)


class RegimeForwardFilter:
    """formulas.md §2.1: forward-filtering / hidden-Markov step. Regime R
    TIDAK teramati langsung — disimpulkan dari seberapa cocok urutan
    condition_state teramati suatu komponen dengan masing-masing Q_r.

    Desain disepakati dengan product owner (Opsi B, regime searah):
    - Regime R sendiri berevolusi over time via generator TERPISAH
      (regime_generator, n_regimes x n_regimes, searah slow->normal->fast,
      absorbing di regime terakhir -- analog CS5 absorbing).
    - Status gabungan (CS, R) direpresentasikan sebagai satu rantai CTMC
      besar (n_regimes * N_STATES status), generatornya Q_joint disusun
      dari dua proses independen (Kronecker-sum): dalam-regime CS berubah
      mengikuti Q_r regime aktif; CS tetap tapi regime berubah mengikuti
      regime_generator.
    - Karena CS TERAMATI PERSIS di tiap inspeksi (bukan observasi bising),
      filtering = majukan keyakinan via expm(Q_joint*dt), lalu "paksa"
      sesuai CS yang benar-benar teramati (zero-out + renormalize)."""

    def build_joint_generator(
        self,
        cs_generators: list[jnp.ndarray],   # Q_r, r=0..n_regimes-1, masing2 5x5
        regime_generator: jnp.ndarray,        # generator regime, n_regimes x n_regimes
    ) -> jnp.ndarray:
        """Susun Q_joint ((n_regimes*N_STATES) x (n_regimes*N_STATES)) dari
        dua proses independen. Indexing status gabungan: combined_idx =
        r * N_STATES + cs (regime-major). Off-diagonal dibangun dulu tanpa
        conditional bergantung nilai (supaya tetap differentiable untuk
        jax.grad di CTMCLatentFittingService nanti), diagonal diturunkan
        di akhir sebagai -rowsum (syarat generator matrix, sama seperti
        GeneratorMatrixParameterization)."""
        n_regimes = len(cs_generators)
        joint_size = n_regimes * N_STATES
        Q_joint = jnp.zeros((joint_size, joint_size))

        # Dalam-regime: CS berubah mengikuti Q_r regime r, regime tetap.
        for r in range(n_regimes):
            Qr_offdiag = cs_generators[r] - jnp.diag(jnp.diag(cs_generators[r]))
            Q_joint = Q_joint.at[
                r * N_STATES:(r + 1) * N_STATES, r * N_STATES:(r + 1) * N_STATES
            ].set(Qr_offdiag)

        # Antar-regime: CS tetap, regime berubah mengikuti regime_generator.
        regime_offdiag = regime_generator - jnp.diag(jnp.diag(regime_generator))
        for cs in range(N_STATES):
            idxs = jnp.array([r * N_STATES + cs for r in range(n_regimes)])
            Q_joint = Q_joint.at[jnp.ix_(idxs, idxs)].add(regime_offdiag)

        row_sums = Q_joint.sum(axis=1)
        Q_joint = Q_joint - jnp.diag(row_sums)
        return Q_joint

    def posterior_regime_probabilities(
        self,
        history: ComponentHistory,
        cs_generators: list[jnp.ndarray],
        regime_generator: jnp.ndarray,
        regime_priors: jnp.ndarray,
    ) -> jnp.ndarray:
        """Return P(R=r | history) — dipakai forecast (§2.4), BUKAN dipakai
        untuk fitting Q_r itu sendiri (itu marginalisasi terpisah, lihat
        CTMCLatentFittingService._joint_log_likelihood).

        Asumsi: history.observations sudah terurut waktu (dijamin oleh
        CTMCDatasetCollector.collect, urut by inspected_at)."""
        n_regimes = len(cs_generators)
        joint_size = n_regimes * N_STATES
        Q_joint = self.build_joint_generator(cs_generators, regime_generator)

        observations = history.observations
        cs0_idx = STATE_INDEX[observations[0][0]]

        belief = jnp.zeros(joint_size)
        for r in range(n_regimes):
            belief = belief.at[r * N_STATES + cs0_idx].set(regime_priors[r])

        prev_time = observations[0][1]
        for condition_state, inspected_at in observations[1:]:
            delta_years = (inspected_at - prev_time).days / 365.25
            P_dt = jax.scipy.linalg.expm(Q_joint * delta_years)
            belief = belief @ P_dt

            cs_idx = STATE_INDEX[condition_state]
            mask = jnp.zeros(joint_size)
            for r in range(n_regimes):
                mask = mask.at[r * N_STATES + cs_idx].set(1.0)
            belief = belief * mask
            belief = belief / belief.sum()

            prev_time = inspected_at

        cs_final_idx = STATE_INDEX[observations[-1][0]]
        posterior = jnp.array([belief[r * N_STATES + cs_final_idx] for r in range(n_regimes)])
        return posterior / posterior.sum()

    def log_likelihood_and_posterior(
        self,
        history: ComponentHistory,
        cs_generators: list[jnp.ndarray],
        regime_generator: jnp.ndarray,
        regime_priors: jnp.ndarray,
    ):
        """formulas.md §2.3: dipakai FITTING (CTMCLatentFittingService),
        BUKAN forecast (§2.4 pakai posterior_regime_probabilities di atas).
        Method TERPISAH (bukan modifikasi method yang sudah teruji) --
        mengulang forward-filter YANG SAMA, tapi mengakumulasi log dari
        konstanta normalisasi tiap langkah sebagai kontribusi log-likelihood
        observasi tersebut (marginalisasi regime laten SUDAH otomatis
        terjadi lewat expm(Q_joint*dt) atas status gabungan -- lihat
        formulas.md §2.4 "mixture, not a single deterministic curve")."""
        n_regimes = len(cs_generators)
        joint_size = n_regimes * N_STATES
        Q_joint = self.build_joint_generator(cs_generators, regime_generator)

        observations = history.observations
        cs0_idx = STATE_INDEX[observations[0][0]]

        belief = jnp.zeros(joint_size)
        for r in range(n_regimes):
            belief = belief.at[r * N_STATES + cs0_idx].set(regime_priors[r])

        log_likelihood = jnp.array(0.0)
        prev_time = observations[0][1]
        for condition_state, inspected_at in observations[1:]:
            delta_years = (inspected_at - prev_time).days / 365.25
            P_dt = jax.scipy.linalg.expm(Q_joint * delta_years)
            belief = belief @ P_dt

            cs_idx = STATE_INDEX[condition_state]
            mask = jnp.zeros(joint_size)
            for r in range(n_regimes):
                mask = mask.at[r * N_STATES + cs_idx].set(1.0)
            belief = belief * mask

            total = jnp.clip(belief.sum(), 1e-300, None)
            log_likelihood = log_likelihood + jnp.log(total)
            belief = belief / total

            prev_time = inspected_at

        cs_final_idx = STATE_INDEX[observations[-1][0]]
        posterior = jnp.array([belief[r * N_STATES + cs_final_idx] for r in range(n_regimes)])
        posterior = posterior / jnp.clip(posterior.sum(), 1e-300, None)
        return log_likelihood, posterior


def history_to_arrays(history: ComponentHistory):
    """Konversi ComponentHistory (list objek Python: string + datetime) jadi
    array JAX murni (cs_indices, delta_years) -- prasyarat untuk versi
    jax.lax.scan/vmap di bawah, yang TIDAK BISA menerima objek Python
    non-tensor. FASE A dari rencana bootstrap vmap+padding (belum dipakai
    fit() utama -- itu tetap pakai RegimeForwardFilter.log_likelihood_and_posterior
    versi loop Python yang sudah teruji, TIDAK disentuh)."""
    cs_indices = jnp.array([STATE_INDEX[state] for state, _ in history.observations], dtype=jnp.int32)
    times = [t for _, t in history.observations]
    delta_years = jnp.array(
        [(times[i + 1] - times[i]).days / 365.25 for i in range(len(times) - 1)],
        dtype=jnp.float64,
    )
    return cs_indices, delta_years


def forward_filter_scan(
    Q_joint: jnp.ndarray,
    cs_indices: jnp.ndarray,
    delta_years: jnp.ndarray,
    regime_priors: jnp.ndarray,
    n_regimes: int,
):
    """FASE A (bootstrap vmap+padding, formulas.md §3.1): versi
    jax.lax.scan dari RegimeForwardFilter.log_likelihood_and_posterior --
    operasi MATEMATIS IDENTIK, cuma dinyatakan dalam array murni (bukan
    loop Python + objek datetime/string) supaya bisa di-jit/vmap. Diverifikasi
    SETARA dengan versi loop lewat regression test sebelum dipakai
    BootstrapResampler (Fase B/C, belum diimplementasikan)."""
    joint_size = n_regimes * N_STATES
    combined_cs = jnp.arange(joint_size) % N_STATES
    combined_regime = jnp.arange(joint_size) // N_STATES

    cs0 = cs_indices[0]
    belief0 = jnp.where(combined_cs == cs0, regime_priors[combined_regime], 0.0)

    def step(carry, xs):
        belief, log_likelihood = carry
        delta_year, cs_idx = xs

        P_dt = jax.scipy.linalg.expm(Q_joint * delta_year)
        belief = belief @ P_dt

        mask = (combined_cs == cs_idx).astype(belief.dtype)
        belief = belief * mask

        total = jnp.clip(belief.sum(), 1e-300, None)
        log_likelihood = log_likelihood + jnp.log(total)
        belief = belief / total

        return (belief, log_likelihood), None

    (belief_final, log_likelihood_final), _ = jax.lax.scan(
        step, (belief0, jnp.array(0.0, dtype=jnp.float64)), (delta_years, cs_indices[1:])
    )

    cs_final = cs_indices[-1]
    belief_reshaped = belief_final.reshape(n_regimes, N_STATES)
    posterior = belief_reshaped[:, cs_final]
    posterior = posterior / jnp.clip(posterior.sum(), 1e-300, None)

    return log_likelihood_final, posterior


def pad_histories_to_arrays(histories: list[ComponentHistory]):
    """FASE B (bootstrap vmap+padding, formulas.md §3.1): ubah histories
    (panjang observasi BEDA-BEDA per komponen) jadi array seragam + mask,
    prasyarat untuk jax.vmap. Padding CS diisi ulang dengan CS TERAKHIR
    komponen tsb (bukan nol/CS1 sembarang) -- aman krn transition_mask
    membuat langkah padding TIDAK ikut mengubah belief/log_likelihood,
    tapi tetap indeks CS yang valid (0..N_STATES-1) supaya tidak
    menghasilkan out-of-bound saat mask dievaluasi."""
    import numpy as np

    max_len = max(len(h.observations) for h in histories)

    n = len(histories)
    cs_indices_np = np.zeros((n, max_len), dtype=np.int32)
    delta_years_np = np.zeros((n, max_len - 1), dtype=np.float64)
    transition_mask_np = np.zeros((n, max_len - 1), dtype=bool)

    for idx, history in enumerate(histories):
        observations = history.observations
        L = len(observations)
        cs_idx_list = [STATE_INDEX[state] for state, _ in observations]
        cs_indices_np[idx, :L] = cs_idx_list
        if L < max_len:
            cs_indices_np[idx, L:] = cs_idx_list[-1]  # padding aman (di-mask)

        times = [t for _, t in observations]
        dt = [(times[i + 1] - times[i]).days / 365.25 for i in range(L - 1)]
        delta_years_np[idx, :len(dt)] = dt
        transition_mask_np[idx, :len(dt)] = True

    return (
        jnp.asarray(cs_indices_np),
        jnp.asarray(delta_years_np),
        jnp.asarray(transition_mask_np),
    )


def forward_filter_scan_masked(
    Q_joint: jnp.ndarray,
    cs_indices: jnp.ndarray,
    delta_years: jnp.ndarray,
    transition_mask: jnp.ndarray,
    regime_priors: jnp.ndarray,
    n_regimes: int,
):
    """FASE B: versi forward_filter_scan (Fase A) yang SADAR MASK -- di
    langkah padding (transition_mask=False), belief dan log_likelihood
    DIJAGA TIDAK BERUBAH lewat jnp.where, bukan diperbarui dengan data
    palsu. Matematis IDENTIK dengan forward_filter_scan untuk observasi
    ASLI (non-padding); diverifikasi lewat regression test terhadap
    forward_filter_scan pada histori tanpa padding."""
    joint_size = n_regimes * N_STATES
    combined_cs = jnp.arange(joint_size) % N_STATES
    combined_regime = jnp.arange(joint_size) // N_STATES

    cs0 = cs_indices[0]
    belief0 = jnp.where(combined_cs == cs0, regime_priors[combined_regime], 0.0)

    def step(carry, xs):
        belief, log_likelihood = carry
        delta_year, cs_idx, is_valid = xs

        P_dt = jax.scipy.linalg.expm(Q_joint * delta_year)
        belief_candidate = belief @ P_dt

        mask_cs = (combined_cs == cs_idx).astype(belief.dtype)
        belief_candidate = belief_candidate * mask_cs

        total = jnp.clip(belief_candidate.sum(), 1e-300, None)
        log_likelihood_candidate = log_likelihood + jnp.log(total)
        belief_candidate = belief_candidate / total

        new_belief = jnp.where(is_valid, belief_candidate, belief)
        new_log_likelihood = jnp.where(is_valid, log_likelihood_candidate, log_likelihood)

        return (new_belief, new_log_likelihood), None

    (belief_final, log_likelihood_final), _ = jax.lax.scan(
        step,
        (belief0, jnp.array(0.0, dtype=jnp.float64)),
        (delta_years, cs_indices[1:], transition_mask),
    )

    # cs_final: CS pada observasi ASLI TERAKHIR (bukan cs_indices[-1] yang
    # bisa jadi padding) -- didapat dari indeks terakhir yang transition_mask
    # True, atau cs_indices[0] kalau tidak ada transisi sama sekali (1 obs).
    has_any_transition = jnp.any(transition_mask)
    last_valid_pos = jnp.max(jnp.where(transition_mask, jnp.arange(transition_mask.shape[0]), -1))
    cs_final = jnp.where(has_any_transition, cs_indices[1:][last_valid_pos], cs0)

    belief_reshaped = belief_final.reshape(n_regimes, N_STATES)
    posterior = belief_reshaped[:, cs_final]
    posterior = posterior / jnp.clip(posterior.sum(), 1e-300, None)

    return log_likelihood_final, posterior


def batched_joint_log_likelihood(
    Q_joint: jnp.ndarray,
    cs_indices_batch: jnp.ndarray,
    delta_years_batch: jnp.ndarray,
    transition_mask_batch: jnp.ndarray,
    regime_priors: jnp.ndarray,
    n_regimes: int,
) -> jnp.ndarray:
    """FASE B: jax.vmap forward_filter_scan_masked atas dimensi histori
    (axis 0 dari *_batch). Q_joint & regime_priors DIBAGI BERSAMA lintas
    histori (in_axes=None) -- ini yang membuatnya cocok dipakai satu
    evaluasi objective untuk SATU parameter model, dievaluasi atas SEMUA
    histori pooled sekaligus secara paralel (bukan loop Python)."""
    log_likelihoods, _ = jax.vmap(
        forward_filter_scan_masked,
        in_axes=(None, 0, 0, 0, None, None),
    )(Q_joint, cs_indices_batch, delta_years_batch, transition_mask_batch, regime_priors, n_regimes)

    return -jnp.sum(log_likelihoods)  # negative total log-likelihood, konsisten _joint_log_likelihood


class CTMCLatentFittingService:
    """architecture.md §3: business logic di service, bukan di Ninja router
    atau job body langsung."""

    def _unpack_params(self, raw_params: jnp.ndarray):
        """Uraikan vektor raw_params GABUNGAN (N_RAW_PARAMS_TOTAL) jadi
        cs_generators (list Q_r, N_REGIMES buah), regime_generator,
        regime_priors -- layout tetap, lihat komentar N_RAW_PARAMS_TOTAL."""
        gen_param = GeneratorMatrixParameterization()
        regime_gen_param = RegimeGeneratorParameterization()

        cs_generators = []
        offset = 0
        for _ in range(N_REGIMES):
            chunk = raw_params[offset:offset + N_RAW_PARAMS_PER_REGIME]
            cs_generators.append(gen_param.unconstrained_to_generator(chunk))
            offset += N_RAW_PARAMS_PER_REGIME

        regime_generator_raw = raw_params[offset:offset + N_RAW_PARAMS_REGIME_GENERATOR]
        regime_generator = regime_gen_param.unconstrained_to_generator(regime_generator_raw)
        offset += N_RAW_PARAMS_REGIME_GENERATOR

        regime_priors_raw = raw_params[offset:offset + N_REGIMES]
        regime_priors = jax.nn.softmax(regime_priors_raw)

        return cs_generators, regime_generator, regime_priors

    def _pack_params(
        self,
        cs_generators: list[jnp.ndarray],
        regime_generator: jnp.ndarray,
        regime_priors: jnp.ndarray,
    ) -> jnp.ndarray:
        """INVERSE dari _unpack_params -- dipakai untuk WARM-START
        BootstrapResampler (formulas.md §3.1) dari parameter tersimpan di
        ctmc_model.parameters (sudah dalam bentuk Q_r/regime_generator/
        regime_priors JADI, bukan raw_params mentah). Layout SAMA persis
        dengan _unpack_params (lihat komentar N_RAW_PARAMS_TOTAL).

        Catatan regime_priors: inverse softmax TIDAK unik (softmax invariant
        terhadap penambahan konstanta ke semua logit) -- log(p) per elemen
        dipakai sebagai SALAH SATU preimage valid; softmax(log(p)) akan
        menghasilkan kembali p yang sama karena softmax menormalkan
        otomatis, jadi ini cukup untuk keperluan warm-start (titik awal
        optimasi), bukan untuk merekonstruksi raw_params ASLI yang dipakai
        fit() (yang mana pun sudah tidak relevan lagi setelah fit selesai)."""
        gen_param = GeneratorMatrixParameterization()
        regime_gen_param = RegimeGeneratorParameterization()

        chunks = [gen_param.generator_to_unconstrained(cs_generators[r]) for r in range(N_REGIMES)]
        chunks.append(regime_gen_param.generator_to_unconstrained(regime_generator))
        chunks.append(jnp.log(jnp.clip(regime_priors, 1e-300, None)))

        return jnp.concatenate(chunks)

    def _joint_log_likelihood(self, raw_params: jnp.ndarray, histories: list[ComponentHistory]) -> jnp.ndarray:
        """formulas.md §2.3: joint MLE atas Q_r semua regime + regime-transition
        rates, marginalisasi regime laten per histori komponen (mixture
        likelihood) — inilah objective yang dioptimasi jax.grad + jaxopt.LBFGS.
        Mengembalikan NEGATIVE total log-likelihood (jaxopt.LBFGS meminimalkan,
        MLE memaksimalkan likelihood -> minimalkan negatifnya)."""
        cs_generators, regime_generator, regime_priors = self._unpack_params(raw_params)
        forward_filter = RegimeForwardFilter()

        total_log_likelihood = jnp.array(0.0)
        for history in histories:
            log_likelihood, _ = forward_filter.log_likelihood_and_posterior(
                history, cs_generators, regime_generator, regime_priors,
            )
            total_log_likelihood = total_log_likelihood + log_likelihood

        return -total_log_likelihood

    def fit(self, organization_id, asset_type: str, component_type: str, component) -> DeteriorationModel:
        """Return DeteriorationModel baru, model_type=CTMC_LATENT.
        parameters JSONB: generator matrices per regime, regime priors/
        transition rates, posterior regime probability KHUSUS `component` ini
        (bukan seluruh pooled dataset), seed dipakai. training_data_hash dari
        SELURUH histories pooled (bukan cuma histori component ini)."""
        collector = CTMCDatasetCollector()
        histories = collector.collect(organization_id, asset_type, component_type)
        if not histories:
            raise ValueError(
                f"Tidak ada histori inspeksi untuk asset_type={asset_type}, "
                f"component_type={component_type} — belum bisa fit CTMC latent."
            )

        training_hash = collector.hash_training_data(histories)
        seed = DETERIORATION["RANDOM_SEED"]

        init_params = 0.1 * jax.random.normal(jax.random.PRNGKey(seed), shape=(N_RAW_PARAMS_TOTAL,))

        # histories ditangkap via closure (BUKAN dilewatkan sebagai argumen
        # traced ke solver.run) -- jaxopt.LBFGS men-JIT fungsi objective-nya;
        # histories berisi objek Python (datetime, string), bukan array JAX,
        # jadi tidak boleh masuk sebagai argumen yang di-trace.
        def objective(params):
            return self._joint_log_likelihood(params, histories)

        solver = jaxopt.LBFGS(
            fun=objective, maxiter=DETERIORATION["CTMC_FIT_LBFGS_MAXITER"], tol=1e-6
        )
        result = solver.run(init_params)
        fitted_params = result.params

        cs_generators, regime_generator, regime_priors = self._unpack_params(fitted_params)

        # Posterior regime KHUSUS component yang sedang di-fit (formulas.md
        # §2.4 butuh ini untuk forecast -- bukan posterior pooled dataset).
        component_history = next(
            (h for h in histories if str(h.component_id) == str(component.id)), None
        )
        if component_history is None:
            raise ValueError(
                f"Component {component.id} tidak ditemukan di pooled histories "
                f"untuk asset_type={asset_type}, component_type={component_type}."
            )

        posterior = RegimeForwardFilter().posterior_regime_probabilities(
            component_history, cs_generators, regime_generator, regime_priors,
        )

        # Versioning: global per component (fix Fase 1 sebelumnya di
        # services.py, dipakai identik di sini -- lihat komentar di sana).
        last_version = (
            DeteriorationModel.objects.filter(component=component)
            .order_by("-model_version")
            .values_list("model_version", flat=True)
            .first()
        ) or 0

        model = DeteriorationModel.objects.create(
            component=component,
            model_type=DeteriorationModel.ModelType.CTMC_LATENT,
            parameters={
                "generators": {
                    REGIME_NAMES[r]: cs_generators[r].tolist() for r in range(N_REGIMES)
                },
                "regime_generator": regime_generator.tolist(),
                "regime_priors": regime_priors.tolist(),
                "regime_posterior_this_component": {
                    REGIME_NAMES[r]: float(posterior[r]) for r in range(N_REGIMES)
                },
                "seed": seed,
            },
            fitted_at=datetime.now(timezone.utc),
            model_version=last_version + 1,
            training_data_hash=training_hash,
        )

        # TransitionMatrix: q_ij marginalisasi posterior regime KHUSUS
        # component ini (untuk heatmap diagnostik, visualization.md §5) --
        # HANYA cell off-diagonal j>i (rate bermakna) yang disimpan; diagonal
        # CTMC (-Σ, bukan rate ke state lain) TIDAK disimpan sebagai
        # rate_or_probability -- beda makna dengan p_ii DTMC (probabilitas
        # tetap di state yang sama). Keputusan desain eksplisit, database.md
        # §4 tidak merinci ini untuk model_type='ctmc_latent'.
        Q_bar = sum(float(posterior[r]) * cs_generators[r] for r in range(N_REGIMES))
        transition_rows = [
            TransitionMatrix(
                model=model,
                from_state=STATES[i],
                to_state=STATES[j],
                rate_or_probability=round(float(Q_bar[i, j]), 6),
            )
            for i, j in OFF_DIAGONAL_CELLS
        ]
        TransitionMatrix.objects.bulk_create(transition_rows)

        return model


class CTMCForecastService:
    """formulas.md §2.4: π(t) = Σ_r P(R=r|history) · [π(0)·P_r(t)], dengan
    P_r(t) = expm(Q_r·t) (§2.2 — matrix exponential, BEDA dari DTMC yang
    pakai matrix power P^t di services.py). Signature dibuat sejajar dengan
    ForecastService (DTMC) agar pemanggilan dari jobs.py konsisten.

    BEDA PENTING vs DTMC: DTMC beriterasi tahun-demi-tahun (pi_t = pi_t @
    p_annual, dipanggil berulang). CTMC TIDAK beriterasi -- expm(Q_r * t)
    dipanggil LANGSUNG dengan t = total tahun sejak sekarang, karena sifat
    matrix exponential CTMC mengizinkan lompat ke waktu berapa pun secara
    langsung tanpa akumulasi galat dari iterasi berulang."""

    def generate(self, model: DeteriorationModel, current_state: str, horizon_years: int = 20):
        params = model.parameters
        cs_generators = [
            jnp.asarray(params["generators"][regime_name]) for regime_name in REGIME_NAMES
        ]
        regime_posterior = jnp.array([
            params["regime_posterior_this_component"][regime_name] for regime_name in REGIME_NAMES
        ])

        pi_0 = jnp.zeros(N_STATES)
        pi_0 = pi_0.at[STATE_INDEX[current_state]].set(1.0)

        current_year = datetime.now(timezone.utc).year
        forecasts = []
        for t in range(1, horizon_years + 1):
            # formulas.md §2.4: π(t) = Σ_r P(R=r|history) · [π(0)·P_r(t)]
            pi_t = jnp.zeros(N_STATES)
            for r in range(N_REGIMES):
                P_r_t = jax.scipy.linalg.expm(cs_generators[r] * t)
                pi_t = pi_t + regime_posterior[r] * (pi_0 @ P_r_t)

            pi_t_np = np.asarray(pi_t)
            # Sanity numerik: expm bisa menghasilkan galat pembulatan kecil
            # (mis. 0.999999997 alih-alih 1.0) -- reproject supaya
            # state_probabilities selalu valid distribusi (jumlah persis 1,
            # non-negatif), TANPA mengubah rumus §2.4 itu sendiri.
            pi_t_np = np.clip(pi_t_np, 0.0, None)
            pi_t_np = pi_t_np / pi_t_np.sum()

            expected_state = STATES[int(np.argmax(pi_t_np))]
            forecasts.append(
                DegradationForecast(
                    model=model,
                    forecast_year=current_year + t,
                    state_probabilities={STATES[i]: round(float(pi_t_np[i]), 5) for i in range(N_STATES)},
                    expected_state=expected_state,
                    confidence_width=None,  # formulas.md §3.2 -- diisi FuzzyBoundsService
                )
            )

        DegradationForecast.objects.bulk_create(forecasts)

        # FETCH ULANG dari database (bug ORM Django 5: bulk_create() dengan
        # PK db_default/RandomUUID() -- lihat apps/core/models.py -- tidak
        # selalu mengambil kembali nilai UUID sungguhan ke objek Python,
        # meninggalkan sentinel DatabaseDefault. Objek in-memory hasil
        # bulk_create TIDAK aman dipakai untuk operasi lanjutan (mis.
        # FuzzyBoundsService.annotate_forecast_confidence_width). Query
        # ulang via (model, forecast_year) -- unique constraint yang sudah
        # ada di skema (database.md §4: forecast_unique_year_per_model).
        forecast_years = [current_year + t for t in range(1, horizon_years + 1)]
        return list(
            DegradationForecast.objects.filter(
                model=model, forecast_year__in=forecast_years
            ).order_by("forecast_year")
        )
