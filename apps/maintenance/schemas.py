"""Ninja schemas untuk app maintenance (Fase 2, scheduling.md/database.md par.5)."""
import uuid
from decimal import Decimal
from typing import Optional

from ninja import Schema


class MaintenancePlanIn(Schema):
    name: str
    budget_total: Decimal
    planning_horizon_years: int
    budget_profile: Optional[dict] = None


class MaintenancePlanOut(Schema):
    id: uuid.UUID
    name: str
    budget_total: Decimal
    planning_horizon_years: int
    status: str
    budget_profile: Optional[dict] = None


class OptimizationRunOut(Schema):
    id: uuid.UUID
    plan_id: uuid.UUID
    solver: str
    status: str
    objective_value: Optional[Decimal] = None
    runtime_seconds: Optional[Decimal] = None
    solver_log_ref: Optional[str] = None


class MaintenanceScheduleOut(Schema):
    id: uuid.UUID
    component_id: uuid.UUID
    intervention_id: uuid.UUID
    scheduled_year: int
    cost: Decimal
    expected_state_after: str
