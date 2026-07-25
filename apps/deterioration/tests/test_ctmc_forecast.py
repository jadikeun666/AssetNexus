"""
formulas.md §2.4 — CTMCForecastService. engineering-rules.md §7: expected
value dihitung tangan via rumus tertutup CTMC 2-status (math.exp, independen
dari jax.scipy.linalg.expm yang dipakai kode), menggunakan skenario posterior
regime terkonsentrasi 100% di satu regime -- mixture §2.4 tereduksi jadi
satu suku, sehingga bisa diverifikasi eksak.
"""
import math
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import numpy as np
import pytest

from apps.assets.models import Asset, AssetComponent
from apps.core.models import Organization, User
from apps.deterioration.models import DeteriorationModel
from apps.deterioration.services_ctmc import N_STATES, CTMCForecastService, REGIME_NAMES


@pytest.fixture
def org():
    return Organization.objects.create(name="Dinas PU Test CTMC Forecast")


def _make_bridge(org, code):
    return Asset.objects.create(
        organization=org, code=code, name=f"Bridge {code}", asset_type=Asset.AssetType.BRIDGE,
        latitude=Decimal("0"), longitude=Decimal("0"), importance_weight=Decimal("5.00"),
    )


def _make_girder(asset):
    return AssetComponent.objects.create(
        asset=asset, component_type="girder", criticality_weight=Decimal("0.250"),
    )


def _zero_generator():
    return [[0.0] * N_STATES for _ in range(N_STATES)]


def _single_transition_generator(rate: float):
    """Generator 5x5 dengan hanya CS1->CS2 aktif (rate q), sisanya nol --
    sama seperti helper di test_regime_forward_filter.py."""
    Q = [[0.0] * N_STATES for _ in range(N_STATES)]
    Q[0][1] = rate
    Q[0][0] = -rate
    return Q


@pytest.mark.django_db
class TestCTMCForecastServiceHandComputed:
    def _make_single_regime_model(self, component, rate: float, active_regime: str):
        """Posterior 100% pada active_regime -- mixture §2.4 tereduksi ke
        satu suku, memungkinkan verifikasi tangan eksak."""
        generators = {name: _zero_generator() for name in REGIME_NAMES}
        generators[active_regime] = _single_transition_generator(rate)

        posterior = {name: 0.0 for name in REGIME_NAMES}
        posterior[active_regime] = 1.0

        return DeteriorationModel.objects.create(
            component=component,
            model_type=DeteriorationModel.ModelType.CTMC_LATENT,
            parameters={
                "generators": generators,
                "regime_generator": [[0.0, 0.0, 0.0]] * 3,
                "regime_priors": [1.0 if r == active_regime else 0.0 for r in REGIME_NAMES],
                "regime_posterior_this_component": posterior,
                "seed": 42,
            },
            fitted_at=datetime.now(timezone.utc),
            model_version=1,
            training_data_hash="dummy-hash-for-test",
        )

    def test_forecast_year_1_matches_hand_computed_exponential(self, org):
        asset = _make_bridge(org, "CTMCFC-A")
        component = _make_girder(asset)
        q = 0.3
        model = self._make_single_regime_model(component, rate=q, active_regime="slow")

        forecasts = CTMCForecastService().generate(model, current_state="CS1", horizon_years=1)

        expected_cs1 = math.exp(-q * 1.0)   # ~0.740818
        expected_cs2 = 1 - math.exp(-q * 1.0)  # ~0.259182

        assert forecasts[0].state_probabilities["CS1"] == pytest.approx(expected_cs1, abs=1e-4)
        assert forecasts[0].state_probabilities["CS2"] == pytest.approx(expected_cs2, abs=1e-4)
        assert forecasts[0].state_probabilities["CS3"] == pytest.approx(0.0, abs=1e-6)
        # 0.7408 > 0.2592 -> argmax jatuh di CS1, BUKAN CS2.
        assert forecasts[0].expected_state == "CS1"

    def test_forecast_year_3_matches_hand_computed_exponential_no_iteration_error_accumulation(self, org):
        # CTMC TIDAK beriterasi -- t=3 dipanggil langsung via expm(Q*3),
        # BUKAN 3x perkalian berturut seperti DTMC. Verifikasi: hasil t=3
        # harus persis math.exp(-q*3), bukan hasil iteratif yang beda.
        asset = _make_bridge(org, "CTMCFC-B")
        component = _make_girder(asset)
        q = 0.2
        model = self._make_single_regime_model(component, rate=q, active_regime="normal")

        forecasts = CTMCForecastService().generate(model, current_state="CS1", horizon_years=3)

        expected_cs1_year3 = math.exp(-q * 3.0)
        expected_cs2_year3 = 1 - math.exp(-q * 3.0)

        assert forecasts[2].forecast_year == datetime.now(timezone.utc).year + 3
        assert forecasts[2].state_probabilities["CS1"] == pytest.approx(expected_cs1_year3, abs=1e-4)
        assert forecasts[2].state_probabilities["CS2"] == pytest.approx(expected_cs2_year3, abs=1e-4)

    def test_forecast_probabilities_sum_to_one_each_year(self, org):
        asset = _make_bridge(org, "CTMCFC-C")
        component = _make_girder(asset)
        model = self._make_single_regime_model(component, rate=0.15, active_regime="fast")

        forecasts = CTMCForecastService().generate(model, current_state="CS1", horizon_years=10)

        assert len(forecasts) == 10
        for f in forecasts:
            total = sum(f.state_probabilities.values())
            assert total == pytest.approx(1.0, abs=1e-3)

    def test_forecast_with_mixture_across_two_regimes_matches_hand_computed_weighted_sum(self, org):
        # Posterior TIDAK terkonsentrasi -- verifikasi mixture §2.4 secara
        # eksplisit: π(t) = w_slow*[π0.expm(Q_slow*t)] + w_fast*[π0.expm(Q_fast*t)]
        asset = _make_bridge(org, "CTMCFC-D")
        component = _make_girder(asset)

        q_slow, q_fast = 0.1, 0.5
        w_slow, w_fast = 0.5, 0.5

        generators = {
            "slow": _single_transition_generator(q_slow),
            "normal": _zero_generator(),
            "fast": _single_transition_generator(q_fast),
        }
        posterior = {"slow": w_slow, "normal": 0.0, "fast": w_fast}

        model = DeteriorationModel.objects.create(
            component=component,
            model_type=DeteriorationModel.ModelType.CTMC_LATENT,
            parameters={
                "generators": generators,
                "regime_generator": [[0.0, 0.0, 0.0]] * 3,
                "regime_priors": [w_slow, 0.0, w_fast],
                "regime_posterior_this_component": posterior,
                "seed": 42,
            },
            fitted_at=datetime.now(timezone.utc),
            model_version=1,
            training_data_hash="dummy-hash-for-test",
        )

        forecasts = CTMCForecastService().generate(model, current_state="CS1", horizon_years=1)

        # Hand-computed: mixture eksplisit atas dua regime.
        expected_cs2 = (
            w_slow * (1 - math.exp(-q_slow * 1.0)) + w_fast * (1 - math.exp(-q_fast * 1.0))
        )
        expected_cs1 = (
            w_slow * math.exp(-q_slow * 1.0) + w_fast * math.exp(-q_fast * 1.0)
        )

        assert forecasts[0].state_probabilities["CS1"] == pytest.approx(expected_cs1, abs=1e-4)
        assert forecasts[0].state_probabilities["CS2"] == pytest.approx(expected_cs2, abs=1e-4)
