"""
formulas.md §2.3 — CTMCDatasetCollector: pooling SAMA seperti DTMC
(per asset_type + component_type), tapi mengembalikan histori LENGKAP
per komponen (bukan pasangan transisi terpotong).
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from apps.assets.models import Asset, AssetComponent
from apps.core.models import Organization, User
from apps.deterioration.services_ctmc import CTMCDatasetCollector
from apps.inspections.models import InspectionRecord


@pytest.fixture
def org():
    return Organization.objects.create(name="Dinas PU Test CTMC")


@pytest.fixture
def inspector(org):
    return User.objects.create(
        keycloak_sub="sub-ctmc-1", organization=org, username="sari",
        email="sari-ctmc@example.id", role=User.Role.INSPECTOR,
    )


def _make_bridge(org, code):
    return Asset.objects.create(
        organization=org, code=code, name=f"Bridge {code}", asset_type=Asset.AssetType.BRIDGE,
        latitude=Decimal("0"), longitude=Decimal("0"), importance_weight=Decimal("5.00"),
    )


def _make_girder(asset):
    return AssetComponent.objects.create(
        asset=asset, component_type="girder", criticality_weight=Decimal("0.250"),
    )


def _make_pier(asset):
    return AssetComponent.objects.create(
        asset=asset, component_type="pier", criticality_weight=Decimal("0.300"),
    )


def _inspect(component, inspector, state, when):
    return InspectionRecord.objects.create(
        component=component, inspector=inspector, inspected_at=when,
        method=InspectionRecord.Method.VISUAL, condition_state=state,
    )


@pytest.mark.django_db
class TestCTMCDatasetCollector:
    def test_collect_groups_full_history_per_component(self, org, inspector):
        asset_a = _make_bridge(org, "CTMC-A")
        asset_b = _make_bridge(org, "CTMC-B")
        comp_a = _make_girder(asset_a)
        comp_b = _make_girder(asset_b)

        t0 = datetime(2023, 1, 1, tzinfo=timezone.utc)
        _inspect(comp_a, inspector, InspectionRecord.ConditionState.CS1, t0)
        _inspect(comp_a, inspector, InspectionRecord.ConditionState.CS1, t0 + timedelta(days=365))
        _inspect(comp_a, inspector, InspectionRecord.ConditionState.CS2, t0 + timedelta(days=730))
        _inspect(comp_a, inspector, InspectionRecord.ConditionState.CS2, t0 + timedelta(days=1095))

        _inspect(comp_b, inspector, InspectionRecord.ConditionState.CS2, t0)
        _inspect(comp_b, inspector, InspectionRecord.ConditionState.CS3, t0 + timedelta(days=365))

        histories = CTMCDatasetCollector().collect(org.id, "bridge", "girder")

        assert len(histories) == 2
        by_id = {h.component_id: h for h in histories}

        history_a = by_id[comp_a.id]
        assert len(history_a.observations) == 4
        assert [obs[0] for obs in history_a.observations] == ["CS1", "CS1", "CS2", "CS2"]
        # Urutan waktu harus naik (§2.1 butuh urutan lintasan, bukan set tak terurut)
        timestamps_a = [obs[1] for obs in history_a.observations]
        assert timestamps_a == sorted(timestamps_a)

        history_b = by_id[comp_b.id]
        assert len(history_b.observations) == 2
        assert [obs[0] for obs in history_b.observations] == ["CS2", "CS3"]

    def test_collect_excludes_other_asset_type_and_component_type(self, org, inspector):
        # formulas.md §2.3 / §1.3: pooling per (asset_type, component_type)
        # SPESIFIK -- tidak boleh bocor lintas cluster.
        asset_bridge = _make_bridge(org, "CTMC-C")
        comp_girder = _make_girder(asset_bridge)
        comp_pier = _make_pier(asset_bridge)  # component_type beda, cluster beda

        t0 = datetime(2023, 1, 1, tzinfo=timezone.utc)
        _inspect(comp_girder, inspector, InspectionRecord.ConditionState.CS1, t0)
        _inspect(comp_pier, inspector, InspectionRecord.ConditionState.CS2, t0)

        histories = CTMCDatasetCollector().collect(org.id, "bridge", "girder")

        assert len(histories) == 1
        assert histories[0].component_id == comp_girder.id

    def test_collect_excludes_sensor_method_records_without_condition_state(self, org, inspector):
        # asset-registry.md §6: method='sensor' tidak membawa condition_state
        # (NULL) -- tidak boleh masuk histori CTMC, sama seperti DTMC.
        asset_a = _make_bridge(org, "CTMC-D")
        comp_a = _make_girder(asset_a)
        t0 = datetime(2023, 1, 1, tzinfo=timezone.utc)
        _inspect(comp_a, inspector, InspectionRecord.ConditionState.CS1, t0)
        InspectionRecord.objects.create(
            component=comp_a, inspector=inspector, inspected_at=t0 + timedelta(days=10),
            method=InspectionRecord.Method.SENSOR, condition_state=None,
        )
        _inspect(comp_a, inspector, InspectionRecord.ConditionState.CS2, t0 + timedelta(days=365))

        histories = CTMCDatasetCollector().collect(org.id, "bridge", "girder")

        assert len(histories) == 1
        assert len(histories[0].observations) == 2  # sensor record dikecualikan

    def test_hash_training_data_is_deterministic_and_order_independent(self, org, inspector):
        # engineering-rules.md §3: hash tidak boleh bergantung urutan dict
        # Python (tidak stabil lintas proses) -- dua kali collect harus
        # menghasilkan hash sama meski urutan list histories berbeda.
        asset_a = _make_bridge(org, "CTMC-E")
        asset_b = _make_bridge(org, "CTMC-F")
        comp_a = _make_girder(asset_a)
        comp_b = _make_girder(asset_b)

        t0 = datetime(2023, 1, 1, tzinfo=timezone.utc)
        _inspect(comp_a, inspector, InspectionRecord.ConditionState.CS1, t0)
        _inspect(comp_a, inspector, InspectionRecord.ConditionState.CS2, t0 + timedelta(days=365))
        _inspect(comp_b, inspector, InspectionRecord.ConditionState.CS2, t0)
        _inspect(comp_b, inspector, InspectionRecord.ConditionState.CS3, t0 + timedelta(days=365))

        collector = CTMCDatasetCollector()
        histories = collector.collect(org.id, "bridge", "girder")
        hash_1 = collector.hash_training_data(histories)

        # Balik urutan list secara manual -- hash harus tetap sama karena
        # hash_training_data() mengurutkan by component_id secara internal.
        reversed_histories = list(reversed(histories))
        hash_2 = collector.hash_training_data(reversed_histories)

        assert hash_1 == hash_2

    def test_hash_training_data_changes_when_new_inspection_added(self, org, inspector):
        asset_a = _make_bridge(org, "CTMC-G")
        comp_a = _make_girder(asset_a)
        t0 = datetime(2023, 1, 1, tzinfo=timezone.utc)
        _inspect(comp_a, inspector, InspectionRecord.ConditionState.CS1, t0)

        collector = CTMCDatasetCollector()
        hash_before = collector.hash_training_data(collector.collect(org.id, "bridge", "girder"))

        _inspect(comp_a, inspector, InspectionRecord.ConditionState.CS2, t0 + timedelta(days=365))
        hash_after = collector.hash_training_data(collector.collect(org.id, "bridge", "girder"))

        assert hash_before != hash_after

    def test_collect_returns_empty_list_when_no_matching_inspections(self, org):
        histories = CTMCDatasetCollector().collect(org.id, "bridge", "girder")
        assert histories == []
