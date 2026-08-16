from datetime import date
from decimal import Decimal

import pytest

from apps.assets.models import Asset, AssetComponent
from apps.core.models import Organization
from apps.sensors.models import SensorDevice
from apps.sensors.services import SensorDeviceService


def _make_component(org_name="Dinas PU Test"):
    org = Organization.objects.create(name=org_name)
    asset = Asset.objects.create(
        organization=org, code=f"BRG-{org_name}", name="Jembatan Test",
        asset_type=Asset.AssetType.BRIDGE,
        latitude=Decimal("-6.914744"), longitude=Decimal("107.609810"),
        importance_weight=Decimal("8.50"),
    )
    component = AssetComponent.objects.create(
        asset=asset, component_type="girder", criticality_weight=Decimal("0.250"),
    )
    return org, component


@pytest.mark.django_db
class TestSensorDeviceService:
    def test_create_device_for_own_org_component(self):
        org, component = _make_component()
        svc = SensorDeviceService()
        device = svc.create(
            organization_id=org.id, created_by=None,
            data={
                "component_id": component.id,
                "device_type": SensorDevice.DeviceType.ACCELEROMETER,
                "install_date": date(2026, 1, 1),
            },
        )
        assert device.id is not None
        assert device.component_id == component.id

    def test_create_device_rejects_component_from_other_org(self):
        _, component_a = _make_component(org_name="Org A")
        org_b, _ = _make_component(org_name="Org B")
        svc = SensorDeviceService()
        from django.http import Http404
        with pytest.raises(Http404):
            svc.create(
                organization_id=org_b.id, created_by=None,
                data={
                    "component_id": component_a.id,
                    "device_type": SensorDevice.DeviceType.STRAIN_GAUGE,
                    "install_date": date(2026, 1, 1),
                },
            )

    def test_list_for_organization_excludes_other_orgs(self):
        org_a, component_a = _make_component(org_name="Org A")
        _, component_b = _make_component(org_name="Org B")
        svc = SensorDeviceService()
        svc.create(
            organization_id=org_a.id, created_by=None,
            data={
                "component_id": component_a.id,
                "device_type": SensorDevice.DeviceType.TILTMETER,
                "install_date": date(2026, 1, 1),
            },
        )
        assert svc.list_for_organization(org_a.id).count() == 1
