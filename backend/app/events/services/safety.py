"""Operational safety check: the Safety Officer's review list, the facts they
assess, their per-factor assessment, and their final decision."""
from app.common.text_validation import validate_descriptive_text
from app.events.services.status import change_status
from app.extensions import db
from app.models.event import Event, EventSafetyAssessment, EventSafetyReview
from app.models.user import User
from app.models.venue import BOOKING_APPROVED
from app.notifications.services import triggers as notifications

SAFETY_DECISIONS = {"approved", "rejected", "changes_requested"}

# Ordered (key, label) pairs: the order is the order the checklist is shown in.
SAFETY_FACTOR_DEFINITIONS = (
    ("expected_attendance", "Expected attendance"),
    ("venue_capacity", "Venue capacity"),
    ("venue_layout", "Venue layout"),
    ("emergency_access", "Emergency access"),
    ("accessibility", "Accessibility requirements"),
    ("equipment_placement", "Equipment placement"),
    ("crowd_movement", "Crowd movement"),
    ("venue_restrictions", "Known venue restrictions"),
)
SAFETY_FACTOR_ORDER = tuple(key for key, _ in SAFETY_FACTOR_DEFINITIONS)
SAFETY_FACTORS = set(SAFETY_FACTOR_ORDER)
FACTOR_OUTCOMES = {"satisfactory", "concern"}
ARRANGEMENTS = {"venue", "equipment"}
MAX_FACTOR_NOTES_LENGTH = 2000


class SafetyReviewConflictError(ValueError):
    """Raised when a review is attempted after the event has left safety_check."""


class SafetyReviewValidationError(ValueError):
    """Raised when a rejection or change request is missing required details.

    Carries every problem at once so the Safety Officer can fix them in one
    pass instead of resubmitting once per missing item.
    """

    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("; ".join(errors))


# ---------------------------------------------------------------------
# Review list and assessment view
# ---------------------------------------------------------------------

def _booked_venue_bookings(event: Event):
    """The venues actually booked for the event (approved bookings only)."""
    return sorted(
        (b for b in event.venue_bookings if b.status == BOOKING_APPROVED),
        key=lambda b: (b.start_datetime is None, b.start_datetime, b.id),
    )


def list_awaiting_safety_check() -> list[dict]:
    """Only events awaiting a safety check, soonest first."""
    events = (
        Event.query.filter_by(status="safety_check")
        .order_by(Event.proposed_date.is_(None), Event.proposed_date, Event.proposed_time, Event.id)
        .all()
    )
    return [_review_list_entry(event) for event in events]


def _review_list_entry(event: Event) -> dict:
    return {
        "id": event.id,
        "name": event.name,
        "proposedDate": event.proposed_date.isoformat() if event.proposed_date else None,
        "proposedTime": event.proposed_time.strftime("%H:%M") if event.proposed_time else None,
        "expectedAttendance": event.expected_attendance,
        "venues": [
            {"id": b.venue_id, "name": b.venue.name if b.venue else None}
            for b in _booked_venue_bookings(event)
        ],
        "coordinatorName": event.coordinator.name if event.coordinator else None,
        "assessmentInProgress": event.safety_assessment is not None,
    }


def build_safety_review(event: Event) -> dict:
    """Everything a Safety Officer needs to assess the event. Missing values
    are returned as None / empty lists; the UI shows them as "Not specified"."""
    venues = []
    for booking in _booked_venue_bookings(event):
        venue = booking.venue
        venues.append(
            {
                "bookingId": booking.id,
                "venueId": booking.venue_id,
                "name": venue.name if venue else None,
                "location": venue.location if venue else None,
                "capacity": venue.capacity if venue else None,
                "supportedLayouts": [
                    {"name": layout.layout_name, "maxCapacity": layout.max_capacity}
                    for layout in (venue.layout_entries if venue else [])
                ],
                "knownRestrictions": venue.known_restrictions if venue else None,
                "operatingHours": venue.operating_hours if venue else None,
                "accessibilityFeatures": list(venue.accessibility_features) if venue else [],
                "startDatetime": booking.start_datetime.isoformat() if booking.start_datetime else None,
                "endDatetime": booking.end_datetime.isoformat() if booking.end_datetime else None,
            }
        )

    return {
        "event": {
            "id": event.id,
            "name": event.name,
            "status": event.status,
            "statusLabel": event.status_label,
            "proposedDate": event.proposed_date.isoformat() if event.proposed_date else None,
            "proposedTime": event.proposed_time.strftime("%H:%M") if event.proposed_time else None,
            "coordinatorName": event.coordinator.name if event.coordinator else None,
        },
        "expectedAttendance": event.expected_attendance,
        "requiredLayout": event.required_layout,
        "accessibilityRequirements": event.accessibility_needs,
        "equipmentRequirements": [
            {
                "id": requirement.id,
                "type": requirement.equipment_type,
                "quantity": requirement.quantity,
                "technicalNotes": requirement.technical_notes,
            }
            for requirement in event.equipment_requirements
        ],
        "venues": venues,
        "factors": [{"key": key, "label": label} for key, label in SAFETY_FACTOR_DEFINITIONS],
        "canAssess": event.status == "safety_check",
        "assessment": event.safety_assessment.to_dict() if event.safety_assessment else None,
        "safetyReviews": [review.to_dict() for review in event.safety_reviews],
    }


# ---------------------------------------------------------------------
# Per-factor assessment
# ---------------------------------------------------------------------

def _validate_factor_assessments(factor_assessments) -> dict:
    """Validate {factor: {"outcome": ..., "notes": ...}} and return a cleaned
    copy in checklist order. A factor with no outcome yet is allowed (the
    assessment may be saved part-way through)."""
    if not isinstance(factor_assessments, dict):
        raise ValueError("Factor assessments must be an object keyed by safety factor")
    unknown = set(factor_assessments) - SAFETY_FACTORS
    if unknown:
        raise ValueError(f"Unknown safety factor(s): {', '.join(sorted(unknown))}")

    cleaned = {}
    for key in SAFETY_FACTOR_ORDER:
        if key not in factor_assessments:
            continue
        entry = factor_assessments[key]
        if not isinstance(entry, dict):
            raise ValueError("Each factor assessment must include an outcome and optional notes")
        outcome = entry.get("outcome")
        if outcome not in FACTOR_OUTCOMES and outcome is not None:
            raise ValueError("Each factor must be marked satisfactory or a concern")
        notes = entry.get("notes")
        if notes is not None and not isinstance(notes, str):
            raise ValueError("Factor notes must be text")
        notes = (notes or "").strip() or None
        if notes and len(notes) > MAX_FACTOR_NOTES_LENGTH:
            raise ValueError(f"Factor notes cannot exceed {MAX_FACTOR_NOTES_LENGTH} characters")
        if outcome is None and notes is None:
            continue
        cleaned[key] = {"outcome": outcome, "notes": notes}
    return cleaned


def save_assessment(event: Event, safety_officer: User, factor_assessments) -> EventSafetyAssessment:
    """Record (or update) the in-progress per-factor assessment."""
    if not safety_officer.has_role("safety_officer"):
        raise PermissionError("Only a Safety Officer can assess event safety")
    if event.status != "safety_check":
        raise SafetyReviewConflictError("Only events awaiting a safety check can be assessed")

    factors = _validate_factor_assessments(factor_assessments)
    assessment = event.safety_assessment
    if assessment is None:
        assessment = EventSafetyAssessment(event_id=event.id, safety_officer_id=safety_officer.id)
        event.safety_assessment = assessment
    assessment.safety_officer_id = safety_officer.id
    assessment.factors = factors
    db.session.commit()
    return assessment


# ---------------------------------------------------------------------
# Decision
# ---------------------------------------------------------------------

def review_safety_check(
    event: Event,
    safety_officer: User,
    decision: str,
    comments: str | None = None,
    assessed_factors: list[str] | None = None,
    concern_factors: list[str] | None = None,
    affected_arrangements: list[str] | None = None,
    factor_assessments: dict | None = None,
) -> Event:
    """Approve, reject or request changes.

    Factors can be given either as per-factor `factor_assessments`
    ({factor: {"outcome", "notes"}}) or, for older clients, as the
    `assessed_factors` / `concern_factors` lists.
    """
    if not safety_officer.has_role("safety_officer"):
        raise PermissionError("Only a Safety Officer can review event safety")
    if event.status != "safety_check":
        raise SafetyReviewConflictError("Only events awaiting a safety check can be reviewed")
    # A decision already made (approved) and not yet acted on by the Coordinator blocks a second review until the event leaves safety_check (confirmed, or reverted to planning).
    latest_review = (
        EventSafetyReview.query.filter_by(event_id=event.id)
        .order_by(EventSafetyReview.id.desc())
        .first()
    )
        
    if latest_review is not None and latest_review.decision == "approved":
        raise SafetyReviewConflictError(
            "This event already has an approved safety review awaiting Coordinator confirmation"
        )
    if decision not in SAFETY_DECISIONS:
        raise ValueError("Decision must be approved, rejected, or changes_requested")
    if comments is not None and not isinstance(comments, str):
        raise ValueError("Safety decision reason must be text")

    factor_notes = None
    if factor_assessments is not None:
        factors = _validate_factor_assessments(factor_assessments)
        assessed_factors = [k for k, v in factors.items() if v["outcome"]]
        concern_factors = [k for k, v in factors.items() if v["outcome"] == "concern"]
        factor_notes = {k: v["notes"] for k, v in factors.items() if v["notes"]} or None

    assessed_factors = _validate_values(assessed_factors, SAFETY_FACTORS, "assessed factors")
    concern_factors = _validate_values(concern_factors, SAFETY_FACTORS, "concern factors")
    affected_arrangements = _validate_values(
        affected_arrangements, ARRANGEMENTS, "affected arrangements"
    )
    if not set(concern_factors).issubset(assessed_factors):
        raise ValueError("Concern factors must also be marked as assessed")

    if decision == "approved":
        missing_factors = SAFETY_FACTORS.difference(assessed_factors)
        if missing_factors:
            raise ValueError("All safety factors must be assessed before approval")
        if concern_factors:
            raise ValueError("An event with safety concerns cannot be approved")
    else:
        errors = []
        try:
            validate_descriptive_text(comments, "safety decision reason")
        except ValueError as e:
            errors.append(str(e))
        if not concern_factors:
            errors.append("Mark at least one safety factor as a concern")
        if not affected_arrangements:
            errors.append("Specify affected arrangements: venue, equipment, or both")
        if errors:
            raise SafetyReviewValidationError(errors)

    review = EventSafetyReview(
        event_id=event.id,
        safety_officer=safety_officer,
        decision=decision,
        comments=comments,
        assessed_factors=assessed_factors,
        concern_factors=concern_factors,
        affected_arrangements=affected_arrangements,
        factor_notes=factor_notes,
    )
    db.session.add(review)
    # The decision now holds the assessment; the next safety check starts fresh.
    if event.safety_assessment is not None:
        db.session.delete(event.safety_assessment)
    if decision != "approved":
        reason = f"Safety check {decision.replace('_', ' ')}"
        reason = f"{reason}: {comments}"
        change_status(event, "planning", changed_by_id=safety_officer.id, reason=reason, notify=False)
        notifications.notify_organiser_of_safety_decision(event, review)
    # On approval, the event stays in "safety_check" — the assigned Coordinator must explicitly mark it Confirmed (Clarification Session 3: "The co-ordinator need to mark the event as confirmed once he sees all approvals are done").
    # Add an explicit commit at the end of review_safety_check, so both approved and non-approved branches persist consistently instead of relying on change_status to do it only for one of them:
    db.session.commit()

    return event


def _validate_values(
    values: list[str] | None, allowed_values: set[str], label: str
) -> list[str]:
    if values is None:
        return []
    if (
        not isinstance(values, list)
        or any(not isinstance(value, str) or value not in allowed_values for value in values)
        or len(values) != len(set(values))
    ):
        raise ValueError(f"{label.capitalize()} must be a list of valid, unique values")
    return values
