"""
Event Review and Approval
---------------------------
- Coordinator reviews full request details (routes.py -> GET /events/<id>)
- Coordinator requests clarification or amendment
- Organiser responds to a clarification request
- Coordinator approves / rejects (with reason) an event request
- Organiser revises and resubmits a rejected request (new record, per
  status enum rule: rejected -> new submitted record on resubmission)
- Organiser views review outcome and comments (routes.py)
"""

from app.common.time import utcnow
from app.common.text_validation import validate_descriptive_text

from app.extensions import db
from app.events.services.assignment import assign_coordinator
from app.events.services.status import InvalidTransitionError, change_status
from app.models.event import Event, EventClarificationResponse, EventReview

from app.events.services.validators import validate_for_submission
from sqlalchemy.exc import IntegrityError

REQUIRED_FOR_SUBMISSION = ["name", "purpose", "description", "proposed_date", "expected_attendance"]
REVIEWABLE_STATUSES = ("submitted", "under_review")

# Once an event reaches any of these, the Organiser can no longer respond
# to an outstanding clarification (the event is no longer actively "in
# review" in any sense that a field edit could still matter).
TERMINAL_STATUSES_BLOCKING_RESPONSE = ("approved", "rejected", "cancelled")

def submit_event(event: Event, organiser_id: int) -> Event:
    if event.organiser_id != organiser_id:
        raise PermissionError("Only the requesting Organiser can submit this request")
    if event.status != "draft":
        raise InvalidTransitionError("Only a draft request can be submitted")

    errors = validate_for_submission(event)
    if errors:
        raise ValueError("Cannot submit: " + "; ".join(errors))

    event.submitted_at = utcnow()
    change_status(event, "submitted", changed_by_id=organiser_id)

    # Coordinator Assignment epic: exactly one Coordinator auto-assigned here,
    # in the same action that moves the event into review (shared contract 3.4).
    #
    # If no active Coordinator is available right now, that is a valid,
    # non-error outcome rather than a failed submission: the request has
    # already been recorded as "submitted" above, so we leave it there,
    # unassigned. It becomes visible to Coordinators as an unassigned event
    # (see assignment.list_unassigned_events / the Planning view) and can be
    # picked up automatically later via assignment.try_assign_and_advance,
    # without ever exposing a manual self-assign step.
    try:
        assign_coordinator(event)
    except ValueError:
        return event

    change_status(event, "under_review", changed_by_id=event.coordinator_id)
    return event


def request_clarification(event: Event, coordinator_id: int, comments: str, editable_fields: list = None) -> Event:
    if event.coordinator_id != coordinator_id:
        raise PermissionError("Only the assigned Coordinator can request clarification")
    if event.status != "under_review":
        raise ValueError("Clarification can only be requested while a request is under review")
    validate_descriptive_text(comments, "clarification comment")

    from app.events.services.drafts import CLARIFICATION_EDITABLE_FIELD_CHOICES  # local import avoids circular import

    editable_fields = editable_fields or []
    invalid_fields = [f for f in editable_fields if f not in CLARIFICATION_EDITABLE_FIELD_CHOICES]
    if invalid_fields:
        raise ValueError(f"Unknown field(s) in editableFields: {', '.join(invalid_fields)}")

    db.session.add(
        EventReview(
            event_id=event.id,
            coordinator_id=coordinator_id,
            action="clarification_requested",
            comments=comments,
            editable_fields=editable_fields,
        )
    )

    # clarification_flag now just means "at least one open request exists" -
    # any number of requests can be open at once, each answered independently
    event.clarification_flag = True
    event.clarification_comments = comments
    db.session.commit()
    return event


def respond_to_clarification(event: Event, organiser_id: int, review_id: int, data: dict) -> Event:
    if event.organiser_id != organiser_id:
        raise PermissionError("Only the requesting Organiser can respond")
    if event.status in TERMINAL_STATUSES_BLOCKING_RESPONSE:
        raise ValueError(f"Cannot respond to a clarification once the request has been {event.status}")

    target_review = next(
        (r for r in event.reviews if r.id == review_id and r.action == "clarification_requested"),
        None,
    )
    if target_review is None:
        raise ValueError("No such clarification request for this event")
    if target_review.withdrawn_at is not None:
        raise ValueError("This clarification request has been withdrawn and no longer needs a response")
    if EventClarificationResponse.query.filter_by(review_id=review_id).first():
        raise ValueError("This clarification has already been responded to")

    comments = data.get("comments", "")
    validate_descriptive_text(comments, "response comment")

    allowed_fields = target_review.editable_fields or []
    restricted_data = {k: v for k, v in data.items() if k in allowed_fields}

    from app.events.services.drafts import _apply_fields

    _apply_fields(event, restricted_data)

    db.session.add(
        EventClarificationResponse(
            event_id=event.id,
            review_id=review_id,
            organiser_id=organiser_id,
            comments=comments,
            updated_fields=restricted_data,
        )
    )

    event.clarification_flag = _has_open_clarification(event, newly_resolved_review_id=review_id)

    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        raise ValueError("This clarification has already been responded to")

    return event

def delete_clarification_request(event: Event, coordinator_id: int, review_id: int) -> Event:
    """The Coordinator withdraws a clarification request they no longer
    need answered. Implemented as a soft delete (withdrawn_at) rather than
    removing the row, so the audit trail still shows it was asked and
    later withdrawn. Only an unanswered request can be withdrawn — once
    responded to, it's part of the permanent review history."""
    if event.coordinator_id != coordinator_id:
        raise PermissionError("Only the assigned Coordinator can delete a clarification request")

    target_review = next(
        (r for r in event.reviews if r.id == review_id and r.action == "clarification_requested"),
        None,
    )
    if target_review is None:
        raise ValueError("No such clarification request for this event")
    if target_review.withdrawn_at is not None:
        raise ValueError("This clarification request has already been deleted")
    if EventClarificationResponse.query.filter_by(review_id=review_id).first():
        raise ValueError("Cannot delete a clarification request that has already been responded to")

    target_review.withdrawn_at = utcnow()
    event.clarification_flag = _has_open_clarification(event, exclude_review_id=review_id)
    if not event.clarification_flag:
        event.clarification_comments = None

    db.session.commit()
    return event

def _has_open_clarification(event: Event, exclude_review_id: int = None, newly_resolved_review_id: int = None) -> bool:
    """True if at least one clarification request is still awaiting a
    response — i.e. not withdrawn and not yet answered."""
    answered_ids = {r.review_id for r in event.clarification_responses}
    if newly_resolved_review_id is not None:
        answered_ids.add(newly_resolved_review_id)
    return any(
        r.action == "clarification_requested"
        and r.withdrawn_at is None
        and r.id != exclude_review_id
        and r.id not in answered_ids
        for r in event.reviews
    )

def approve_event(event: Event, coordinator_id: int, comments: str = None) -> Event:
    if event.coordinator_id != coordinator_id:
        raise PermissionError("Only the assigned Coordinator can approve this request")
    if event.status != "under_review":
        raise ValueError("Only a request under review can be approved")

    event.review_outcome = "approved"
    event.review_reason = comments
    event.review_timestamp = utcnow()
    event.review_coordinator_id = coordinator_id
    db.session.add(
        EventReview(event_id=event.id, coordinator_id=coordinator_id, action="approved", comments=comments)
    )
    change_status(event, "approved", changed_by_id=coordinator_id, reason=comments)
    change_status(event, "planning", changed_by_id=coordinator_id, reason="Approval recorded; planning may begin")
    return event


def reject_event(event: Event, coordinator_id: int, reason: str) -> Event:
    if event.coordinator_id != coordinator_id:
        raise PermissionError("Only the assigned Coordinator can reject this request")
    if event.status not in REVIEWABLE_STATUSES:
        raise ValueError("Only a request under review can be rejected")
    validate_descriptive_text(reason, "rejection reason")

    event.review_outcome = "rejected"
    event.review_reason = reason
    event.review_timestamp = utcnow()
    event.review_coordinator_id = coordinator_id
    db.session.add(
        EventReview(event_id=event.id, coordinator_id=coordinator_id, action="rejected", comments=reason)
    )
    change_status(event, "rejected", changed_by_id=coordinator_id, reason=reason)
    return event


def resubmit_rejected_event(original: Event, organiser_id: int, data: dict) -> Event:
    if original.organiser_id != organiser_id:
        raise PermissionError("Only the requesting Organiser can resubmit this request")
    if original.status != "rejected":
        raise ValueError("Only a rejected request can be resubmitted")
    if not can_be_resubmitted(original):
        raise ValueError("This request has already been resubmitted. Please open the latest resubmission instead.")

    new_event = Event(
        organiser_id=organiser_id,
        status="draft",
        resubmitted_from_event_id=original.id,
        name=original.name,
        purpose=original.purpose,
        description=original.description,
        category=original.category,
        proposed_date=original.proposed_date,
        proposed_time=original.proposed_time,
        expected_attendance=original.expected_attendance,
        capacity_needed=original.capacity_needed,
        required_layout=original.required_layout,
        accessibility_needs=original.accessibility_needs,
        required_facilities=original.required_facilities,
        registration_required=original.registration_required,
        intended_capacity=original.intended_capacity,
    )
    db.session.add(new_event)
    db.session.commit()

    from app.events.services.drafts import _apply_fields  # local import avoids circular import

    if data:
        _apply_fields(new_event, data)
        db.session.commit()

    return submit_event(new_event, organiser_id)

def get_clarification_thread(event: Event) -> list:
    responses_by_review = {r.review_id: r for r in event.clarification_responses}
    thread = []
    for entry in event.reviews:
        if entry.action != "clarification_requested":
            continue
        response = responses_by_review.get(entry.id)
        thread.append(
            {
                "reviewId": entry.id,
                "request": {
                    "coordinatorId": entry.coordinator_id,
                    "comments": entry.comments,
                    "editableFields": entry.editable_fields or [],
                    "createdAt": entry.created_at.isoformat() if entry.created_at else None,
                },
                "response": response.to_dict() if response else None,
                "withdrawn": entry.withdrawn_at is not None,
            }
        )
    return thread

def can_be_resubmitted(event: Event) -> bool:
    """True if this rejected request has not yet been resubmitted. Each
    rejected request can be resubmitted exactly once, but a resubmission
    that is itself rejected becomes a new rejected request with its own
    single resubmission available, so a chain can keep growing for as
    long as the Coordinator keeps rejecting."""
    if event.status != "rejected":
        return False
    return Event.query.filter_by(resubmitted_from_event_id=event.id).first() is None

def get_full_review_history(event: Event) -> list:
    """Walks back through the resubmission chain (rejected -> new record,
    via resubmitted_from_event_id) and returns every review action across
    all generations, oldest first, each tagged with which event it
    belongs to. This is how "previous rejection reasons and review
    history" stay visible even though a resubmission is a brand-new
    Event row, not a reused one."""
    chain = []
    current = event
    visited = set()
    while current is not None and current.id not in visited:
        visited.add(current.id)
        chain.append(current)
        if current.resubmitted_from_event_id is None:
            break
        current = Event.query.get(current.resubmitted_from_event_id)
    chain.reverse()  # oldest first

    history = []
    for e in chain:
        for r in e.reviews:
            history.append(
                {
                    "eventId": e.id,
                    "reviewId": r.id,
                    "action": r.action,
                    "coordinatorId": r.coordinator_id,
                    "comments": r.comments,
                    "createdAt": r.created_at.isoformat() if r.created_at else None,
                    "isCurrentSubmission": e.id == event.id,
                }
            )
    return history


def get_prior_rejection_decisions(event: Event) -> list:
    """Every review decision (approved/rejected) from EARLIER generations
    in the resubmission chain - not the current event's own decision.
    The current event's live status/reviewDecision (already in
    Event.to_dict()) always reflects the latest submission on its own;
    this is purely the historical trail behind it."""
    chain = []
    current = event
    visited = set()
    while current is not None and current.id not in visited:
        visited.add(current.id)
        if current.id != event.id and current.review_outcome:
            chain.append(
                {
                    "eventId": current.id,
                    "outcome": current.review_outcome,
                    "reason": current.review_reason,
                    "timestamp": current.review_timestamp.isoformat() if current.review_timestamp else None,
                    "coordinatorId": current.review_coordinator_id,
                    "coordinatorName": current.review_coordinator.name if current.review_coordinator else None,
                }
            )
        if current.resubmitted_from_event_id is None:
            break
        current = Event.query.get(current.resubmitted_from_event_id)
    chain.reverse()
    return chain