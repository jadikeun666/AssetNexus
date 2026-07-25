import uuid
from decimal import Decimal
from typing import Optional

from ninja import Schema


class AssetIn(Schema):
    code: str
    name: str
    asset_type: str
    latitude: Decimal
    longitude: Decimal
    construction_year: Optional[int] = None
    design_life_years: Optional[int] = None
    importance_weight: Decimal
    status: str = "active"


class AssetOut(Schema):
    id: uuid.UUID
    code: str
    name: str
    asset_type: str
    latitude: Decimal
    longitude: Decimal
    construction_year: Optional[int]
    design_life_years: Optional[int]
    importance_weight: Decimal
    status: str


class AssetComponentIn(Schema):
    asset_id: uuid.UUID
    parent_component_id: Optional[uuid.UUID] = None
    component_type: str
    criticality_weight: Decimal


class AssetComponentOut(Schema):
    id: uuid.UUID
    asset_id: uuid.UUID
    parent_component_id: Optional[uuid.UUID]
    component_type: str
    criticality_weight: Decimal
