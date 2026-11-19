from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest

from apps.assets.models import AssetComponent
from apps.digitaltwin.services_anomaly_markers import AnomalyMarkerService
from apps.digitaltwin.tests.test_services_anomaly_markers import (
    _make_component,
    _make_device,
)
from apps.sensors.models import AnomalyEvent
from config.assetnexus import DIGITAL_TWIN

T0 = datetime(2026, 8, 19, tzinfo=timezone.utc)


def _event(device, minutes, severity=AnomalyEvent.Severity.MEDIUM, **kw):
    return AnomalyEvent.objects.create(
        device=device, detected_at=T0 + timedelta(minutes=minutes),
        detection_method=AnomalyEvent.DetectionMethod.THRESHOLD,
        severity=severity, **kw,
    )


@pytest.mark.django_db
class TestListForComponent:
    def test_newest_first_and_capped_by_config(self, monkeypatch):
        org, asset, component = _make_component("Events Cap")
        device = _make_device(component)
        for m in range(4):
            _event(device, m)
        monkeypatch.setitem(DIGITAL_TWIN, "ANOMALY_PANEL_MAX_EVENTS", 2)

        events = AnomalyMarkerService().list_for_component(org.id, asset.id, "girder")
        assert [e["detected_at"] for e in events] == [
            T0 + timedelta(minutes=3), T0 + timedelta(minutes=2),
        ]

    def test_includes_resolved_and_low_with_notes(self):
        org, asset, component = _make_component("Events Resolved")
        device = _make_device(component)
        _event(device, 1, AnomalyEvent.Severity.LOW,
               resolved=True, resolution_notes="Sensor dikalibrasi ulang")

        events = AnomalyMarkerService().list_for_component(org.id, asset.id, "girder")
        assert len(events) == 1
        assert events[0]["resolved"] is True
        assert events[0]["severity"] == "low"
        assert events[0]["resolution_notes"] == "Sensor dikalibrasi ulang"

    def test_filters_by_component_type(self):
        org, asset, girder = _make_component("Events Filter")
        pier = AssetComponent.objects.create(
            asset=asset, component_type="pier", criticality_weight=Decimal("0.250"),
        )
        _event(_make_device(girder), 1)
        _event(_make_device(pier), 2)

        svc = AnomalyMarkerService()
        assert len(svc.list_for_component(org.id, asset.id, "girder")) == 1
        assert len(svc.list_for_component(org.id, asset.id, "pier")) == 1
        assert svc.list_for_component(org.id, asset.id, "abutment") == []

    def test_other_organization_sees_nothing(self):
        org, asset, component = _make_component("Events Org")
        _event(_make_device(component), 1)
        assert AnomalyMarkerService().list_for_component(uuid4(), asset.id, "girder") == []
