"""
formulas.md §1 — Discrete-Time Markov Chain baseline.

Dipakai ketika komponen punya < config.assetnexus.DETERIORATION
["MIN_INSPECTIONS_FOR_CTMC"] catatan inspeksi (formulas.md §2 kebalikannya
adalah syarat CTMC — Fase 1). Fitting selalu POOLED per (asset_type,
component_type), never across the whole portfolio (formulas.md §1.3).
"""
import hashlib
from datetime import datetime, timezone

import jax.numpy as jnp
import numpy as np

from config.assetnexus import DETERIORATION

from apps.inspections.models import InspectionRecord

from .models import ConditionStateChoices, DegradationForecast, DeteriorationModel, TransitionMatrix

STATES = [c.value for c in ConditionStateChoices]  # ["CS1","CS2","CS3","CS4","CS5"]
STATE_INDEX = {s: i for i, s in enumerate(STATES)}
N_STATES = len(STATES)


def reproject_to_stochastic(P: np.ndarray) -> np.ndarray:
    """
    formulas.md §1.4: "guarding against complex-valued results by
    re-projecting to the nearest valid stochastic matrix (row-normalize,
    clip negatives to 0)".
    """
    P = np.clip(P, 0.0, None)
    row_sums = P.sum(axis=1, keepdims=True)
    row_sums[row_sums == 0] = 1.0
    return P / row_sums


def normalize_interval(p_delta: np.ndarray, delta_t: float) -> np.ndarray:
    """
    formulas.md §1.4: P_annual = P_Δt ^ (1/Δt), via eigendecomposition in
    JAX (jax.numpy.linalg.eig), guarded against complex results.
    """
    # Toleransi dilebarkan dari 1e-9 ke 1e-2 (~3-4 hari): interval inspeksi
    # lapangan realistis jarang persis 365.25 hari. Di bawah toleransi ini,
    # P dianggap sudah annual dan JALUR EIGENDECOMPOSITION DIHINDARI --
    # penting karena matriks P bisa defective/near-defective (mis. baris
    # CS2->CS3 penuh + fallback identitas di baris lain membentuk struktur
    # mirip blok Jordan), yang membuat jax.numpy.linalg.eig numerically
    # unstable untuk delta_t yang cuma meleset sedikit dari 1.0.
    if abs(delta_t - 1.0) < DETERIORATION["ANNUAL_INTERVAL_TOLERANCE_YEARS"]:
        return p_delta.copy()

    P = jnp.asarray(p_delta)
    eigvals, eigvecs = jnp.linalg.eig(P)
    eigvals_annual = eigvals ** (1.0 / delta_t)
    P_annual_complex = eigvecs @ jnp.diag(eigvals_annual) @ jnp.linalg.inv(eigvecs)
    P_annual_real = np.asarray(jnp.real(P_annual_complex))
    return reproject_to_stochastic(P_annual_real)


class DiscreteMarkovFittingService:
    """architecture.md §3: business logic here, never in the Ninja router
    or in the Dramatiq job body directly."""

    def _collect_transition_pairs(self, organization_id, asset_type: str, component_type: str):
        """
        formulas.md §1.3: pooled fitting across ALL components sharing the
        same asset_type AND component_type within the organization.
        Returns list of (from_state, to_state, delta_years) tuples plus
        the raw (component_id, inspected_at, condition_state) rows used,
        for hashing.
        """
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

        pairs = []
        by_component = {}
        for r in records:
            by_component.setdefault(r["component_id"], []).append(r)

        for component_records in by_component.values():
            for prev, curr in zip(component_records, component_records[1:]):
                from_state, to_state = prev["condition_state"], curr["condition_state"]
                delta_days = (curr["inspected_at"] - prev["inspected_at"]).days
                if delta_days <= 0:
                    continue
                delta_years = delta_days / 365.25
                # formulas.md §1.1: "deterioration-only" assumption —
                # transitions that appear to improve (j < i) are excluded
                # from pooled fitting rather than violating the monotone
                # model structure. These typically reflect an intervention
                # having occurred between inspections, not natural
                # deterioration, and interventions are modeled separately
                # (scheduling.md), not folded into the baseline DTMC.
                if STATE_INDEX[to_state] < STATE_INDEX[from_state]:
                    continue
                pairs.append((from_state, to_state, delta_years))

        return pairs, records

    def _count_transitions(self, pairs) -> np.ndarray:
        counts = np.zeros((N_STATES, N_STATES))
        for from_state, to_state, _ in pairs:
            counts[STATE_INDEX[from_state], STATE_INDEX[to_state]] += 1
        return counts

    def _mle_transition_matrix(self, counts: np.ndarray) -> np.ndarray:
        """
        formulas.md §1.3: MLE over observed state pairs = row-normalized
        transition counts. CS5 is forced absorbing (formulas.md §2.1)
        regardless of counts, since no outflow from CS5 is permitted
        under the monotone model other than the explicit
        replacement/retirement path (asset-registry.md §3), which is not
        a state transition and is never fit from inspection pairs.
        """
        P = np.zeros((N_STATES, N_STATES))
        for i in range(N_STATES):
            row_total = counts[i].sum()
            if row_total > 0:
                P[i] = counts[i] / row_total
            else:
                # Tidak ada data transisi teramati dari state ini di
                # pooled dataset — fallback aman: anggap tetap (p_ii=1),
                # bukan menebak distribusi degradasi tanpa bukti data.
                P[i, i] = 1.0
        # CS5 absorbing, ditegakkan eksplisit terlepas dari counts:
        P[STATE_INDEX["CS5"]] = 0.0
        P[STATE_INDEX["CS5"], STATE_INDEX["CS5"]] = 1.0
        return P

    def _average_interval_years(self, pairs) -> float:
        deltas = [dt for _, _, dt in pairs]
        return float(np.mean(deltas)) if deltas else 1.0

    def _hash_training_data(self, records) -> str:
        """engineering-rules.md §3: training_data_hash enables exact
        audit of "what data produced this forecast"."""
        payload = "|".join(
            f'{r["component_id"]}:{r["inspected_at"].isoformat()}:{r["condition_state"]}'
            for r in records
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def fit(self, organization_id, asset_type: str, component_type: str, component) -> DeteriorationModel:
        pairs, raw_records = self._collect_transition_pairs(organization_id, asset_type, component_type)
        if not pairs:
            raise ValueError(
                f"Tidak ada pasangan transisi teramati untuk asset_type={asset_type}, "
                f"component_type={component_type} — belum bisa fit DTMC baseline."
            )

        counts = self._count_transitions(pairs)
        delta_t = self._average_interval_years(pairs)
        p_delta = self._mle_transition_matrix(counts)
        p_annual = normalize_interval(p_delta, delta_t)
        training_hash = self._hash_training_data(raw_records)

        # Versi dihitung GLOBAL per component (lintas model_type), BUKAN
        # per (component, model_type) -- wajib konsisten dengan
        # UniqueConstraint(fields=["component", "model_version"]) di
        # DeteriorationModel.Meta, yang juga global per component
        # (database.md §4: "Monotonically incrementing per component").
        # Kalau di-filter per model_type, begitu ctmc_latent/fuzzy_markov
        # di-fit untuk component yang sama (Fase 1), masing-masing bisa
        # menghitung "versi berikutnya" yang identik dan bentrok INSERT
        # dengan versi discrete_markov yang sudah ada untuk component itu.
        last_version = (
            DeteriorationModel.objects.filter(component=component)
            .order_by("-model_version")
            .values_list("model_version", flat=True)
            .first()
        ) or 0

        model = DeteriorationModel.objects.create(
            component=component,
            model_type=DeteriorationModel.ModelType.DISCRETE_MARKOV,
            parameters={"p_annual": p_annual.tolist(), "delta_t_used_years": delta_t},
            fitted_at=datetime.now(timezone.utc),
            model_version=last_version + 1,
            training_data_hash=training_hash,
        )

        # formulas.md §1.1: hanya cell j >= i yang valid (deterioration-only)
        transition_rows = [
            TransitionMatrix(
                model=model,
                from_state=STATES[i],
                to_state=STATES[j],
                rate_or_probability=round(float(p_annual[i, j]), 6),
            )
            for i in range(N_STATES)
            for j in range(N_STATES)
            if j >= i
        ]
        TransitionMatrix.objects.bulk_create(transition_rows)

        return model


class ForecastService:
    """formulas.md §1.5: π(t) = π(0) · P_annual^t."""

    def generate(self, model: DeteriorationModel, current_state: str, horizon_years: int = 20):
        p_annual = np.array(model.parameters["p_annual"])
        pi_t = np.zeros(N_STATES)
        pi_t[STATE_INDEX[current_state]] = 1.0

        current_year = datetime.now(timezone.utc).year
        forecasts = []
        for t in range(1, horizon_years + 1):
            pi_t = pi_t @ p_annual
            expected_state = STATES[int(np.argmax(pi_t))]
            forecasts.append(
                DegradationForecast(
                    model=model,
                    forecast_year=current_year + t,
                    state_probabilities={STATES[i]: round(float(pi_t[i]), 5) for i in range(N_STATES)},
                    expected_state=expected_state,
                    confidence_width=None,  # formulas.md §3.2 — diisi Fase 1
                )
            )
        DegradationForecast.objects.bulk_create(forecasts)

        # FETCH ULANG dari database -- bug ORM Django 5 yang sama dengan
        # yang ditemukan & diperbaiki di CTMCForecastService.generate()
        # (services_ctmc.py): bulk_create() dengan PK db_default/RandomUUID()
        # (apps/core/models.py) tidak selalu mengambil kembali UUID
        # sungguhan ke objek Python. Perbaikan minimal murni bug ORM,
        # TIDAK mengubah logic fitting/forecast DTMC apa pun.
        forecast_years = [current_year + t for t in range(1, horizon_years + 1)]
        return list(
            DegradationForecast.objects.filter(
                model=model, forecast_year__in=forecast_years
            ).order_by("forecast_year")
        )
