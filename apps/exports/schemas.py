import uuid
from typing import Optional

from ninja import Schema


class ExportJobRequestIn(Schema):
    component_id: uuid.UUID


class PdfMaintenancePlanRequestIn(Schema):
    plan_id: uuid.UUID


class ExportJobOut(Schema):
    id: uuid.UUID
    export_type: str
    reference_id: uuid.UUID
    status: str
    file_ref: Optional[str]
    failure_reason: str
