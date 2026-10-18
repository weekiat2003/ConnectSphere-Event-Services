from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required

from app.auth.decorators import roles_required
from app.events.services import assignment, drafts, review, safety
from app.events.services import status as status_service
from app.events.services import update as update_service

from app.models.event import Event
from app.models.user import User

from app.common.text_validation import validate_descriptive_text

events_bp = Blueprint("events", __name__)


def _current_user():
    return User.query.get(int(get_jwt_identity()))

def _require_confirmation(event, data, action_label):
    """Approve/reject/cancel all require an explicit confirmation before
    taking effect — always, and with an extra warning when the request
    still has an unresolved clarification."""
    if data.get("confirmed") is True:
        return None
    if event.clarification_flag:
        message = f"This request has an unresolved clarification. Are you sure you want to {action_label} it anyway?"
    else:
        message = f"Are you sure you want to {action_label} this request?"
    return (
        jsonify(
            {
                "requiresConfirmation": True,
                "hasUnresolvedClarification": event.clarification_flag,
                "message": message,
            }
        ),
        409,
    )

INTERNAL_ROLES = ("event_coordinator", "venue_staff", "technical_support_staff", "safety_officer")



def _can_view(event: Event, user: User) -> bool:
    if user.has_role("event_organiser") and event.organiser_id == user.id:
        return True
    if event.status == "draft":
        return False  # drafts are private to their organiser until submitted
    return any(user.has_role(r) for r in INTERNAL_ROLES)


# ---------------------------------------------------------------------
# Event Request Creation / Draft Event Requests
# ---------------------------------------------------------------------

@events_bp.post("/drafts")
@roles_required("event_organiser")
def create_draft():
    user = _current_user()
    event = drafts.create_draft(user.id, request.get_json() or {})
    return jsonify(event.to_dict()), 201


@events_bp.get("/drafts")
@roles_required("event_organiser")
def list_drafts():
    user = _current_user()
    return jsonify([e.to_dict() for e in drafts.list_drafts(user.id)]), 200


@events_bp.put("/drafts/<int:event_id>")
@roles_required("event_organiser")
def update_draft(event_id):
    user = _current_user()
    event = Event.query.get(event_id)
    if not event or event.organiser_id != user.id:
        return jsonify({"error": "Draft not found"}), 404
    try:
        event = drafts.update_draft(event, request.get_json() or {})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify(event.to_dict()), 200


@events_bp.delete("/drafts/<int:event_id>")
@roles_required("event_organiser")
def delete_draft(event_id):
    user = _current_user()
    event = Event.query.get(event_id)
    if not event or event.organiser_id != user.id:
        return jsonify({"error": "Draft not found"}), 404
    try:
        drafts.delete_draft(event)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    return "", 204


@events_bp.post("")
@roles_required("event_organiser")
def create_event():
    """Creates an event request. Pass `"submit": true` in the body to submit
    it directly instead of leaving it as a draft (Event Request Creation:
    'Submit a newly created event request directly')."""
    user = _current_user()
    data = request.get_json() or {}
    submit_now = data.pop("submit", False)

    event = drafts.create_draft(user.id, data)
    if submit_now:
        try:
            event = review.submit_event(event, user.id)
        except (ValueError, PermissionError) as e:
            return jsonify({"error": str(e), "event": event.to_dict()}), 400

    return jsonify(event.to_dict()), 201


@events_bp.post("/<int:event_id>/submit")
@roles_required("event_organiser")
def submit_event_route(event_id):
    user = _current_user()
    event = Event.query.get(event_id)
    if not event or event.organiser_id != user.id:
        return jsonify({"error": "Event not found"}), 404
    try:
        event = review.submit_event(event, user.id)
    except (ValueError, PermissionError) as e:
        return jsonify({"error": str(e)}), 400
    return jsonify(event.to_dict()), 200


# ---------------------------------------------------------------------
# Viewing (Event Status Management + Coordinator Assignment visibility)
# ---------------------------------------------------------------------

@events_bp.get("/mine")
@roles_required("event_organiser")
def my_events():
    """Organiser views the status of all their own requests, most recent
    first. Defaults to the full list as a plain array (unchanged from
    before, so existing callers keep working); pass ?page=&per_page= to
    page through large result sets (Story 2, AC4). Pagination metadata
    goes in response headers so the response body is always an array."""
    user = _current_user()
    query = Event.query.filter_by(organiser_id=user.id).order_by(Event.updated_at.desc())

    page = request.args.get("page", type=int)
    per_page = request.args.get("per_page", type=int)

    if page is None and per_page is None:
        events = query.all()
        response = jsonify([e.to_dict() for e in events])
        response.headers["X-Total-Count"] = str(len(events))
        return response, 200

    page = max(page or 1, 1)
    per_page = min(max(per_page or 20, 1), 100)
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)

    response = jsonify([e.to_dict() for e in pagination.items])
    response.headers["X-Total-Count"] = str(pagination.total)
    response.headers["X-Page"] = str(pagination.page)
    response.headers["X-Per-Page"] = str(per_page)
    response.headers["X-Total-Pages"] = str(pagination.pages)
    return response, 200


@events_bp.get("/assigned")
@roles_required("event_coordinator")
def assigned_events():
    """Coordinator views requests currently assigned to them."""
    user = _current_user()
    query = Event.query.filter_by(coordinator_id=user.id).order_by(Event.updated_at.desc())
    return jsonify([e.to_dict() for e in query.all()]), 200


@events_bp.get("")
@jwt_required()
def list_all_events():
    """Single combined calendar view: Coordinators, Venue Staff and Technical
    Support Staff can see all events for planning purposes, read-only unless
    they are the event's assigned Coordinator (Q&A #30/#34)."""
    user = _current_user()
    if not any(user.has_role(r) for r in INTERNAL_ROLES):
        return jsonify({"error": "Forbidden"}), 403
    events = (
        Event.query.filter(Event.status != "draft")
        .order_by(Event.proposed_date.asc())
        .all()
    )
    return jsonify([e.to_dict() for e in events]), 200


@events_bp.get("/<int:event_id>")
@jwt_required()
def get_event(event_id):
    user = _current_user()
    event = Event.query.get(event_id)
    if not event or not _can_view(event, user):
        return jsonify({"error": "Event not found"}), 404
    payload = event.to_dict()
    payload["canResubmit"] = review.can_be_resubmitted(event)
    return jsonify(payload), 200

# ---------------------------------------------------------------------
# Event Information Management
# ---------------------------------------------------------------------

@events_bp.put("/<int:event_id>/update")
@roles_required("event_coordinator")
def update_event_route(event_id):
    """US-1 core-field edit + US-4 confirmed-event lock."""
    user = _current_user()
    event = Event.query.get(event_id)
    if not event:
        return jsonify({"error": "Event not found"}), 404

    data = request.get_json() or {}
    changes = data.get("fields", {})
    offline_review_confirmed = data.get("offlineReviewConfirmed", False)

    try:
        event = update_service.update_event_fields(event, user, changes, offline_review_confirmed)
    except update_service.EventLockedError as e:
        return jsonify({"error": str(e)}), 423
    except PermissionError as e:
        return jsonify({"error": str(e)}), 403
    except update_service.EventNotEditableStatusError as e:
        return jsonify({"error": str(e)}), 409
    except update_service.OfflineReviewNotConfirmedError as e:
        return jsonify({"error": str(e)}), 400
    except update_service.EventValidationError as e:
        return jsonify({"errors": e.field_errors}), 400

    return jsonify(event.to_dict()), 200


# ---------------------------------------------------------------------
# Event Review and Approval
# ---------------------------------------------------------------------

def _nil_if_empty(value):
    """Returns value unchanged, or the literal string "NIL" if it counts as
    empty for the review display: None, a blank string, or an empty
    list/dict. 0 and False are real values and are kept as-is."""
    if value is None:
        return "NIL"
    if isinstance(value, str) and value.strip() == "":
        return "NIL"
    if isinstance(value, (list, dict)) and len(value) == 0:
        return "NIL"
    return value


def _format_proposed_date_time(event: Event):
    if event.proposed_date and event.proposed_time:
        return f"{event.proposed_date.isoformat()} {event.proposed_time.isoformat()}"
    if event.proposed_date:
        return event.proposed_date.isoformat()
    if event.proposed_time:
        return event.proposed_time.isoformat()
    return None


def _venue_requirements_value(event: Event):
    sub_fields = {
        "capacityNeeded": _nil_if_empty(event.capacity_needed),
        "requiredLayout": _nil_if_empty(event.required_layout),
        "requiredFacilities": _nil_if_empty(event.required_facilities or []),
    }
    if all(v == "NIL" for v in sub_fields.values()):
        return "NIL"
    return sub_fields


def _equipment_requirements_value(event: Event):
    if not event.equipment_requirements:
        return "NIL"
    return [
        {
            "type": _nil_if_empty(item.equipment_type),
            "quantity": _nil_if_empty(item.quantity),
            "technicalNotes": _nil_if_empty(item.technical_notes),
        }
        for item in event.equipment_requirements
    ]


def _registration_requirements_value(event: Event):
    if not event.registration_required:
        return "NIL"
    return {
        "registrationRequired": True,
        "intendedCapacity": _nil_if_empty(event.intended_capacity),
    }


def _build_display_fields(event: Event):
    """Coordinator reviews full request details — the exact set of fields
    the Organiser submitted, each under its exact title, with "NIL" wherever
    a value was not provided."""
    return [
        {"title": "Event name", "value": _nil_if_empty(event.name)},
        {"title": "Event purpose", "value": _nil_if_empty(event.purpose)},
        {"title": "Event description", "value": _nil_if_empty(event.description)},
        {"title": "Proposed date and time", "value": _nil_if_empty(_format_proposed_date_time(event))},
        {"title": "Expected attendance", "value": _nil_if_empty(event.expected_attendance)},
        {"title": "Venue requirements", "value": _venue_requirements_value(event)},
        {"title": "Accessibility requirements", "value": _nil_if_empty(event.accessibility_needs)},
        {"title": "Equipment requirements", "value": _equipment_requirements_value(event)},
        {"title": "Registration requirements", "value": _registration_requirements_value(event)},
    ]


@events_bp.get("/<int:event_id>/review")
@roles_required("event_coordinator")
def review_event_details(event_id):
    """Coordinator reviews full request details.

    - AC1/AC6: restricted to the Event Coordinator role by @roles_required;
      any other role is rejected with 403 before this function even runs.
    - AC3/AC4/AC5/AC7: a GET request returns every field the Organiser
      submitted plus the current status, in a plain read-only payload —
      there is no corresponding write endpoint for this route, so the
      review itself can never mutate the request. `displayFields` lists
      each field under its exact title (Event name, Event purpose, Event
      description, Proposed date and time, Expected attendance, Venue
      requirements, Accessibility requirements, Equipment requirements,
      Registration requirements), showing "NIL" for anything the
      Organiser did not provide.
    - AC8: `availableActions` tells the caller which of request-clarification
      /approve/reject are currently valid, based on status.
    """
    user = _current_user()
    event = Event.query.get(event_id)
    if not event:
        return jsonify({"error": "Event not found"}), 404

    payload = event.to_dict()
    payload["displayFields"] = _build_display_fields(event)
    payload["reviewHistory"] = [r.to_dict() for r in event.reviews]
    payload["fullReviewHistory"] = review.get_full_review_history(event)
    payload["priorDecisions"] = review.get_prior_rejection_decisions(event)
    payload["clarificationThread"] = review.get_clarification_thread(event)
    payload["isAssignedCoordinator"] = event.coordinator_id == user.id
    payload["availableActions"] = (
        ["request_clarification", "approve", "reject"]
        if event.status in ("submitted", "under_review")
        else []
    )
    payload["canResubmit"] = review.can_be_resubmitted(event)
    return jsonify(payload), 200

@events_bp.post("/<int:event_id>/clarification")
@roles_required("event_coordinator")
def request_clarification(event_id):
    user = _current_user()
    event = Event.query.get(event_id)
    if not event:
        return jsonify({"error": "Event not found"}), 404
    data = request.get_json() or {}
    try:
        event = review.request_clarification(
            event,
            user.id,
            data.get("comments", ""),
            editable_fields=data.get("editableFields", []),
        )
    except (ValueError, PermissionError) as e:
        return jsonify({"error": str(e)}), 400
    return jsonify(event.to_dict()), 200


@events_bp.post("/<int:event_id>/clarification/response")
@roles_required("event_organiser")
def respond_clarification(event_id):
    user = _current_user()
    event = Event.query.get(event_id)
    if not event:
        return jsonify({"error": "Event not found"}), 404

    data = request.get_json() or {}
    review_id = data.get("reviewId")
    if not review_id:
        return (
            jsonify({"error": "reviewId is required to identify which clarification request you are answering"}),
            400,
        )

    try:
        event = review.respond_to_clarification(event, user.id, review_id, data)
    except (ValueError, PermissionError) as e:
        return jsonify({"error": str(e)}), 400

    payload = event.to_dict()
    payload["clarificationThread"] = review.get_clarification_thread(event)
    return jsonify(payload), 200

@events_bp.delete("/<int:event_id>/clarification/<int:review_id>")
@roles_required("event_coordinator")
def delete_clarification_request_route(event_id, review_id):
    user = _current_user()
    event = Event.query.get(event_id)
    if not event:
        return jsonify({"error": "Event not found"}), 404
    try:
        event = review.delete_clarification_request(event, user.id, review_id)
    except (ValueError, PermissionError) as e:
        return jsonify({"error": str(e)}), 400
    payload = event.to_dict()
    payload["clarificationThread"] = review.get_clarification_thread(event)
    return jsonify(payload), 200

@events_bp.post("/<int:event_id>/approve")
@roles_required("event_coordinator")
def approve_event_route(event_id):
    user = _current_user()
    event = Event.query.get(event_id)
    if not event:
        return jsonify({"error": "Event not found"}), 404
    data = request.get_json() or {}

    confirmation = _require_confirmation(event, data, "approve")
    if confirmation:
        return confirmation

    try:
        event = review.approve_event(event, user.id, data.get("comments"))
    except (ValueError, PermissionError) as e:
        return jsonify({"error": str(e)}), 400
    return jsonify(event.to_dict()), 200


@events_bp.post("/<int:event_id>/reject")
@roles_required("event_coordinator")
def reject_event_route(event_id):
    user = _current_user()
    event = Event.query.get(event_id)
    if not event:
        return jsonify({"error": "Event not found"}), 404
    data = request.get_json() or {}

    confirmation = _require_confirmation(event, data, "reject")
    if confirmation:
        return confirmation

    try:
        event = review.reject_event(event, user.id, data.get("reason"))
    except (ValueError, PermissionError) as e:
        return jsonify({"error": str(e)}), 400
    return jsonify(event.to_dict()), 200


@events_bp.post("/<int:event_id>/resubmit")
@roles_required("event_organiser")
def resubmit_event_route(event_id):
    user = _current_user()
    original = Event.query.get(event_id)
    if not original:
        return jsonify({"error": "Event not found"}), 404
    try:
        new_event = review.resubmit_rejected_event(original, user.id, request.get_json() or {})
    except (ValueError, PermissionError) as e:
        return jsonify({"error": str(e)}), 400
    return jsonify(new_event.to_dict()), 201


@events_bp.get("/<int:event_id>/outcome")
@jwt_required()
def review_outcome(event_id):
    """Organiser views review outcome and comments (also usable by the
    assigned Coordinator to review their own decision history)."""
    user = _current_user()
    event = Event.query.get(event_id)
    if not event or not _can_view(event, user):
        return jsonify({"error": "Event not found"}), 404
    return (
        jsonify(
            {
                "status": event.status,
                "reviewDecision": event.to_dict()["reviewDecision"],
                "clarificationFlag": event.clarification_flag,
                "clarificationComments": event.clarification_comments,
                "reviewHistory": [r.to_dict() for r in event.reviews],
                "fullReviewHistory": review.get_full_review_history(event),
                "priorDecisions": review.get_prior_rejection_decisions(event),
                "clarificationThread": review.get_clarification_thread(event),
                "canResubmit": review.can_be_resubmitted(event),
            }
        ),
        200,
    )


# ---------------------------------------------------------------------
# Coordinator Assignment
# ---------------------------------------------------------------------

@events_bp.get("/unassigned")
@roles_required("event_coordinator")
def unassigned_events():
    """Coordinators view events with no assigned Coordinator, for planning
    visibility only — there is no self-assign step (Q&A #6/#13/#22)."""
    events = assignment.list_unassigned_events()
    return jsonify([e.to_dict() for e in events]), 200


@events_bp.get("/calendar")
@roles_required("event_coordinator")
def coordinator_calendar_route():
    """Coordinator's own calendar: events they currently own plus events
    they previously coordinated before being reassigned off, the latter
    flagged isReadOnly (Q&A #39)."""
    user = _current_user()
    return jsonify(assignment.coordinator_calendar(user.id)), 200


@events_bp.post("/<int:event_id>/auto-assign")
@roles_required("event_coordinator")
def auto_assign_event(event_id):
    """Lets any Coordinator trigger a retry of automatic assignment for an
    event that was submitted while no Coordinator was available (still
    rule-based via get_next_coordinator — not a manual pick or self-assign;
    see assignment.try_assign_and_advance)."""
    event = Event.query.get(event_id)
    if not event:
        return jsonify({"error": "Event not found"}), 404
    try:
        event = assignment.try_assign_and_advance(event)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify(event.to_dict()), 200


@events_bp.post("/<int:event_id>/reassign")
@roles_required("event_coordinator")
def reassign_event(event_id):
    """Reassignment after offline agreement: the currently assigned
    Coordinator hands the event to a named replacement Coordinator
    (Q&A #6/#13/#22 — no accept/decline step, agreement happens outside
    the system first)."""
    user = _current_user()
    event = Event.query.get(event_id)
    if not event:
        return jsonify({"error": "Event not found"}), 404
    if event.coordinator_id != user.id:
        return jsonify({"error": "Only the currently assigned Coordinator can hand off this event"}), 403

    data = request.get_json() or {}
    new_coordinator = User.query.get(data.get("newCoordinatorId"))
    if not new_coordinator or not new_coordinator.has_role("event_coordinator"):
        return jsonify({"error": "newCoordinatorId must reference an active Event Coordinator"}), 400

    event = assignment.reassign_coordinator(event, new_coordinator)
    return jsonify(event.to_dict()), 200


# ---------------------------------------------------------------------
# Event Status Management
# ---------------------------------------------------------------------

@events_bp.post("/<int:event_id>/status")
@roles_required("event_coordinator")
def change_event_status(event_id):
    """Generic status-change endpoint for the assigned Coordinator, covering
    cancellation and confirmed -> planning reversion on major change. Approve
    /reject/submit have their own dedicated endpoints above since they carry
    extra business rules (reason required, review-decision snapshot, etc.)."""
    user = _current_user()
    event = Event.query.get(event_id)
    if not event:
        return jsonify({"error": "Event not found"}), 404
    if event.coordinator_id != user.id:
        return jsonify({"error": "Only the assigned Coordinator can change this event's status"}), 403

    data = request.get_json() or {}
    new_status = data.get("status")
    reason = data.get("reason")

    try:
        if new_status == "planning" and event.status == "confirmed":
            event = status_service.revert_to_planning(
                event, user.id, reason or "Major change requires re-planning"
            )
        else:
            event = status_service.change_status(event, new_status, user.id, reason)
    except status_service.InvalidTransitionError as e:
        return jsonify({"error": str(e)}), 400

    return jsonify(event.to_dict()), 200

@events_bp.post("/<int:event_id>/cancel")
@roles_required("event_coordinator")
def cancel_event_route(event_id):
    """Dedicated cancel endpoint, mirroring approve/reject: requires
    confirmation and a descriptive reason, same rules as rejection."""
    user = _current_user()
    event = Event.query.get(event_id)
    if not event:
        return jsonify({"error": "Event not found"}), 404
    if event.coordinator_id != user.id:
        return jsonify({"error": "Only the assigned Coordinator can cancel this event"}), 403

    data = request.get_json() or {}
    confirmation = _require_confirmation(event, data, "cancel")
    if confirmation:
        return confirmation

    reason = data.get("reason")
    try:
        validate_descriptive_text(reason, "cancellation reason")
        event = status_service.change_status(event, "cancelled", user.id, reason)
    except (ValueError, status_service.InvalidTransitionError) as e:
        return jsonify({"error": str(e)}), 400

    return jsonify(event.to_dict()), 200


@events_bp.post("/<int:event_id>/safety-review")
@roles_required("safety_officer")
def review_event_safety(event_id):
    event = Event.query.get(event_id)
    if not event:
        return jsonify({"error": "Event not found"}), 404

    user = _current_user()
    data = request.get_json() or {}
    try:
        event = safety.review_safety_check(
            event,
            user,
            data.get("decision"),
            data.get("comments"),
            data.get("assessedFactors"),
            data.get("concernFactors"),
            data.get("affectedArrangements"),
        )
    except safety.SafetyReviewConflictError as e:
        return jsonify({"error": str(e)}), 409
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    return jsonify(event.to_dict()), 200