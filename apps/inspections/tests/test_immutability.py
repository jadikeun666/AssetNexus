from datetime import datetime, timezone
from decimal import Decimal

import pytest
from django.db import IntegrityError, transaction

from apps.assets.models import Asset, AssetComponent
from apps.core.models import Organization, User
from apps.inspections.models import InspectionRecord


@pytest.fixture
def component():
    org = Organization.objects.create(name="Org")
    asset = Asset.objects.create(
        organization=org, code="BRG-100", name="Test", asset_type=Asset.AssetType.BRIDGE,
        latitude=Decimal("0"), longitude=Decimal("0"), importance_weight=Decimal("5.00"),
    )
    return AssetComponent.objects.create(asset=asset, component_type="girder", criticality_weight=Decimal("0.250"))


@pytest.fixture
def inspector(component):
    return User.objects.create(
        keycloak_sub="test-sub-1", organization=component.asset.organization,
        username="sari", email="sari@example.id", role=User.Role.INSPECTOR,
    )


@pytest.mark.django_db
class TestInspectionImmutability:
    def test_create_succeeds(self, component, inspector):
        record = InspectionRecord.objects.create(
            component=component, inspector=inspector,
            inspected_at=datetime.now(timezone.utc),
            method=InspectionRecord.Method.VISUAL,
            condition_state=InspectionRecord.ConditionState.CS2,
        )
        assert record.id is not None

    def test_update_is_blocked(self, component, inspector):
        record = InspectionRecord.objects.create(
            component=component, inspector=inspector,
            inspected_at=datetime.now(timezone.utc),
            method=InspectionRecord.Method.VISUAL,
            condition_state=InspectionRecord.ConditionState.CS2,
        )
        record.notes = "mencoba menyelipkan edit"
        with pytest.raises(ValueError):
            record.save()

    def test_delete_is_blocked(self, component, inspector):
        record = InspectionRecord.objects.create(
            component=component, inspector=inspector,
            inspected_at=datetime.now(timezone.utc),
            method=InspectionRecord.Method.VISUAL,
            condition_state=InspectionRecord.ConditionState.CS2,
        )
        with pytest.raises(ValueError):
            record.delete()

    def test_correction_is_a_new_row_via_supersedes(self, component, inspector):
        original = InspectionRecord.objects.create(
            component=component, inspector=inspector,
            inspected_at=datetime.now(timezone.utc),
            method=InspectionRecord.Method.VISUAL,
            condition_state=InspectionRecord.ConditionState.CS3,
        )
        correction = InspectionRecord.objects.create(
            component=component, inspector=inspector,
            inspected_at=datetime.now(timezone.utc),
            method=InspectionRecord.Method.VISUAL,
            condition_state=InspectionRecord.ConditionState.CS2,
            supersedes=original,
        )
        assert correction.supersedes_id == original.id
        assert InspectionRecord.objects.count() == 2  # original tetap ada, tak tersentuh

    def test_condition_state_null_iff_sensor_method(self, component, inspector):
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                InspectionRecord.objects.create(
                    component=component, inspector=inspector,
                    inspected_at=datetime.now(timezone.utc),
                    method=InspectionRecord.Method.VISUAL,
                    condition_state=None,  # invalid: method non-sensor wajib punya condition_state
                )
