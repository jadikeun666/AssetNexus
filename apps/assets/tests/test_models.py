from decimal import Decimal

import pytest
from django.db import IntegrityError, transaction

from apps.assets.models import Asset, AssetComponent
from apps.core.models import Organization


@pytest.mark.django_db
class TestAsset:
    def test_asset_gets_db_generated_uuid(self):
        org = Organization.objects.create(name="Dinas PU Test")
        asset = Asset.objects.create(
            organization=org, code="BRG-001", name="Jembatan Cikapundung",
            asset_type=Asset.AssetType.BRIDGE,
            latitude=Decimal("-6.914744"), longitude=Decimal("107.609810"),
            importance_weight=Decimal("8.50"),
        )
        assert asset.id is not None

    def test_importance_weight_out_of_range_rejected(self):
        # asset-registry.md §5: importance_weight harus di [1, 10]
        org = Organization.objects.create(name="Dinas PU Test")
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                Asset.objects.create(
                    organization=org, code="BRG-002", name="Invalid weight asset",
                    asset_type=Asset.AssetType.BRIDGE,
                    latitude=Decimal("0"), longitude=Decimal("0"),
                    importance_weight=Decimal("11.00"),
                )

    def test_organization_scoped_manager_excludes_other_orgs(self):
        org_a = Organization.objects.create(name="Org A")
        org_b = Organization.objects.create(name="Org B")
        Asset.objects.create(
            organization=org_a, code="A-1", name="Asset A", asset_type=Asset.AssetType.BRIDGE,
            latitude=Decimal("0"), longitude=Decimal("0"), importance_weight=Decimal("5.00"),
        )
        Asset.objects.create(
            organization=org_b, code="B-1", name="Asset B", asset_type=Asset.AssetType.BRIDGE,
            latitude=Decimal("0"), longitude=Decimal("0"), importance_weight=Decimal("5.00"),
        )
        assert Asset.objects.for_organization(org_a.id).count() == 1
        assert Asset.objects.for_organization(org_a.id).first().code == "A-1"


@pytest.mark.django_db
class TestAssetComponentHierarchy:
    def test_self_referential_hierarchy(self):
        org = Organization.objects.create(name="Org")
        asset = Asset.objects.create(
            organization=org, code="BRG-003", name="Test Bridge",
            asset_type=Asset.AssetType.BRIDGE, latitude=Decimal("0"), longitude=Decimal("0"),
            importance_weight=Decimal("5.00"),
        )
        superstructure = AssetComponent.objects.create(
            asset=asset, component_type="superstructure", criticality_weight=Decimal("0.400"),
        )
        girder = AssetComponent.objects.create(
            asset=asset, parent_component=superstructure,
            component_type="girder", criticality_weight=Decimal("0.250"),
        )
        assert girder.parent_component_id == superstructure.id
        assert superstructure.sub_components.count() == 1

    def test_scoped_manager_follows_fk_chain_to_organization(self):
        org_a = Organization.objects.create(name="Org A")
        org_b = Organization.objects.create(name="Org B")
        asset_a = Asset.objects.create(
            organization=org_a, code="A-2", name="A", asset_type=Asset.AssetType.BRIDGE,
            latitude=Decimal("0"), longitude=Decimal("0"), importance_weight=Decimal("5.00"),
        )
        AssetComponent.objects.create(asset=asset_a, component_type="pier", criticality_weight=Decimal("0.300"))
        assert AssetComponent.objects.for_organization(org_a.id).count() == 1
        assert AssetComponent.objects.for_organization(org_b.id).count() == 0
