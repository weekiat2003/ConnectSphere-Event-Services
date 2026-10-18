"""Safety Officer decisions for events whose arrangements are ready."""
from app.common.text_validation import validate_descriptive_text
from app.events.services import status as status_service
from app.events.services.status import change_status
from app.extensions import db
from app.models.event import Event, EventSafetyReview
from app.models.user import User

SAFETY_DECISIONS = {"approved", "rejected", "changes_requested"}
SAFETY_FACTORS = {
    "expected_attendance",
    "venue_capacity",
    "venue_layout",
    "emergency_access",
    "accessibility",
    "equipment_placement",
    "crowd_movement",
    "venue_restrictions",
}
ARRANGEMENTS = {"venue", "equipment"}


class SafetyReviewConflictError(ValueError):
    """Raised when a review is attempted after the event has left safety_check."""


def review_safety_check(
    event: Event,
    safety_officer: User,
    decision: str,
    comments: str | None = None,
    assessed_factors: list[str] | None = None,
    concern_factors: list[str] | None = None,
    affected_arrangements: list[str] | None = None,
) -> Event:
    if not safety_officer.has_role("safety_officer"):
        raise PermissionError("Only a Safety Officer can review event safety")
    if event.status != "safety_check":
        raise SafetyReviewConflictError("Only events awaiting a safety check can be reviewed")
    if decision not in SAFETY_DECISIONS:
        raise ValueError("Decision must be approved, rejected, or changes_requested")
    if comments is not None and not isinstance(comments, str):
        raise ValueError("Safety decision reason must be text")

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
        validate_descriptive_text(comments, "safety decision reason")
        if not concern_factors:
            raise ValueError("Mark at least one safety factor as a concern")
        if not affected_arrangements:
            raise ValueError("Specify affected arrangements: venue, equipment, or both")

    review = EventSafetyReview(
        event_id=event.id,
        safety_officer=safety_officer,
        decision=decision,
        comments=comments,
        assessed_factors=assessed_factors,
        concern_factors=concern_factors,
        affected_arrangements=affected_arrangements,
    )
    db.session.add(review)
    if decision == "approved":
        status_service.confirm_after_safety_approval(event, review)
    else:
        reason = f"Safety check {decision.replace('_', ' ')}"
        reason = f"{reason}: {comments}"
        change_status(event, "planning", changed_by_id=safety_officer.id, reason=reason)
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