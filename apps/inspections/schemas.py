import uuid
from datetime import datetime
from typing import Optional

from ninja import Schema


class InspectionRecordIn(Schema):
    component_id: uuid.UUID
    inspector_id: uuid.UUID
    inspected_at: datetime
    method: str
    condition_state: Optional[str] = None
    notes: str = ""
    photo_refs: list[str] = []
    supersedes_id: Optional[uuid.UUID] = None


class InspectionRecordOut(Schema):
    id: uuid.UUID
    component_id: uuid.UUID
    inspector_id: uuid.UUID
    inspected_at: datetime
    method: str
    condition_state: Optional[str]
    notes: str
    photo_refs: list[str]
    supersedes_id: Optional[uuid.UUID]
