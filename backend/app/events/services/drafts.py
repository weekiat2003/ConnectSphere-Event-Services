"""
Event Request Creation / Draft Event Requests
-----------------------------------------------
- Create event request with core details, date/time/attendance, venue
  requirements, equipment/technical requirements, registration requirements
- Save an in-progress event request as a draft
- View / edit / submit / delete a saved draft
"""
from app.extensions import db
from app.models.event import Event, EventEquipmentRequirement
from datetime import date, time, datetime


CORE_FIELDS = ["name", "purpose", "description", "category"]
SCHEDULE_FIELDS = [
    "proposed_date",
    "proposed_time",
    "proposed_end_date",
    "proposed_end_time",
    "expected_attendance",
]
VENUE_FIELDS = ["capacity_needed", "required_layout", "accessibility_needs", "required_facilities"]
REGISTRATION_FIELDS = ["registration_required", "intended_capacity"]

EDITABLE_FIELDS = CORE_FIELDS + SCHEDULE_FIELDS + VENUE_FIELDS + REGISTRATION_FIELDS

# Fields a Coordinator may grant an Organiser permission to edit while
# responding to a clarification request (Event Review and Approval).
CLARIFICATION_EDITABLE_FIELD_CHOICES = EDITABLE_FIELDS + ["equipment_requirements"]

def _parse_date(value):
    if value in (None, ""):
        return None

    if isinstance(value, date):
        return value

    return datetime.strptime(value, "%Y-%m-%d").date()

def _parse_time(value):
    if value in (None, ""):
        return None

    if isinstance(value, time):
        return value

    return datetime.strptime(value, "%H:%M").time()

def _apply_fields(event: Event, data: dict):
    for field in EDITABLE_FIELDS:
        if field in data:
            value = data[field]

            if field in ("proposed_date", "proposed_end_date"):
                value = _parse_date(value)

            elif field in ("proposed_time", "proposed_end_time"):
                value = _parse_time(value)

            setattr(event, field, value)

    # Default end date to start date if no end date is provided.
    if not event.proposed_end_date and event.proposed_date:
        event.proposed_end_date = event.proposed_date

    if "equipment_requirements" in data:
        event.equipment_requirements = []
        for item in data["equipment_requirements"]:
            event.equipment_requirements.append(
                EventEquipmentRequirement(
                    equipment_type=item.get("type"),
                    quantity=item.get("quantity", 0),
                    technical_notes=item.get("technicalNotes"),
                )
            )


def create_draft(organiser_id: int, data: dict) -> Event:
    event = Event(organiser_id=organiser_id, status="draft")
    _apply_fields(event, data)
    db.session.add(event)
    db.session.commit()
    return event


def update_draft(event: Event, data: dict) -> Event:
    if event.status != "draft":
        raise ValueError("Only a draft request can be edited this way")
    _apply_fields(event, data)
    db.session.commit()
    return event


def delete_draft(event: Event):
    if event.status != "draft":
        raise ValueError("Only a draft request can be deleted")
    db.session.delete(event)
    db.session.commit()


def list_drafts(organiser_id: int):
    return (
        Event.query.filter_by(organiser_id=organiser_id, status="draft")
        .order_by(Event.updated_at.desc())
        .all()
    )
