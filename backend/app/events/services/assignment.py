"""
Coordinator Assignment
-----------------------
- Automatic coordinator assignment on submission (fair, workload-based;
  exactly one Coordinator per event, no self-assign / accept-decline step)
- Coordinator views assigned requests (routes.py)
- Reassign coordinator after offline agreement
- Coordinators view unassigned/all events for planning visibility (routes.py)
- Previous coordinator retains read-only visibility after reassignment
"""
from app.common.time import utcnow

from sqlalchemy import func

from app.events.services.status import change_status
from app.extensions import db
from app.common.text_validation import validate_descriptive_text
from app.models.event import (
    REASSIGNMENT_CLOSED,
    REASSIGNMENT_COMPLETED,
    REASSIGNMENT_DECLINED,
    REASSIGNMENT_PENDING,
    REASSIGNMENT_WITHDRAWN,
    CoordinatorReassignmentRequest,
    Event,
    EventCoordinatorHistory,
)
from app.models.user import Role, User
from app.notifications.services import triggers as notifications

OPEN_STATUSES = ("under_review", "approved", "planning")


def _active_coordinators():
    return (
        User.query.join(User.roles)
        .filter(Role.name == "event_coordinator", User.is_active.is_(True))
        .all()
    )


def get_next_coordinator():
    """Picks the active Coordinator with the fewest currently open assigned
    events (workload-based, deterministic tie-break by id for fairness)."""
    coordinators = _active_coordinators()
    if not coordinators:
        return None

    counts = (
        db.session.query(Event.coordinator_id, func.count(Event.id))
        .filter(Event.status.in_(OPEN_STATUSES))
        .group_by(Event.coordinator_id)
        .all()
    )
    workload = {c.id: 0 for c in coordinators}
    for coordinator_id, count in counts:
        if coordinator_id in workload:
            workload[coordinator_id] = count

    return min(coordinators, key=lambda c: (workload[c.id], c.id))


def assign_coordinator(event: Event, coordinator: User = None, assignment_type: str = "auto",
                       previous_coordinator_id: int = None, assigned_by_id: int = None) -> Event:
    coordinator = coordinator or get_next_coordinator()
    if coordinator is None:
        raise ValueError("No active Event Coordinator is available for assignment")

    event.coordinator_id = coordinator.id
    db.session.add(
        EventCoordinatorHistory(
            event_id=event.id,
            coordinator_id=coordinator.id,
            assignment_type=assignment_type,
            assigned_by=assigned_by_id,
        )
    )
    # Notification System (ISP-105, ISP-103 AC5): tell the new Coordinator,
    # the previous one (if any) and the organiser, and clear the Leads' queue notices.
    notifications.notify_coordinator_assignment(event, coordinator, previous_coordinator_id)
    db.session.commit()
    return event


def reassign_coordinator(event: Event, new_coordinator: User, assigned_by_id: int = None) -> Event:
    """Reassignment is agreed offline between coordinators; this records the
    handover once that agreement has been made (per Q&A #6/#13/#22)."""
    previous_coordinator_id = event.coordinator_id
    open_entry = (
        EventCoordinatorHistory.query.filter_by(
            event_id=event.id, coordinator_id=event.coordinator_id, unassigned_at=None
        ).first()
    )
    if open_entry:
        open_entry.unassigned_at = utcnow()

    return assign_coordinator(
        event, coordinator=new_coordinator, assignment_type="reassignment",
        previous_coordinator_id=previous_coordinator_id, assigned_by_id=assigned_by_id,
    )


# ---------------------------------------------------------------------
# Event Coordinator Lead (Notification System, ISP-103 / ISP-105)
# ---------------------------------------------------------------------

class AlreadyAssignedError(ValueError):
    """Another Lead got there first. Carries who it went to."""

    def __init__(self, event: Event):
        self.coordinator_name = event.coordinator.name if event.coordinator else None
        super().__init__(f"This request is already assigned to {self.coordinator_name or 'a Coordinator'}")


def _require_active_coordinator(coordinator: User):
    if coordinator is None or not coordinator.is_active or not coordinator.has_role("event_coordinator"):
        raise ValueError("coordinatorId must reference an active Event Coordinator")


def lead_assign(event: Event, coordinator: User, dry_run: bool = False, assigned_by_id: int = None) -> Event:
    """A Lead assigns an Unassigned request: it moves to under_review
    ("Assigned"), leaves the queue, the Coordinator is notified, and every
    Lead's queue notification for it is cleared. dry_run checks only."""
    locked = db.session.query(Event).filter_by(id=event.id).with_for_update().first()
    if locked.coordinator_id is not None:
        raise AlreadyAssignedError(locked)
    if locked.status != "submitted":
        raise ValueError("Only a submitted, unassigned request can be assigned")
    _require_active_coordinator(coordinator)
    if dry_run:
        return locked

    assign_coordinator(locked, coordinator=coordinator, assignment_type="lead",
                       assigned_by_id=assigned_by_id)
    change_status(locked, "under_review", changed_by_id=assigned_by_id or coordinator.id,
                  reason=f"Assigned to {coordinator.name} by a Coordinator Lead")
    return locked


def lead_reassign(event: Event, new_coordinator: User, dry_run: bool = False,
                  assigned_by_id: int = None) -> Event:
    """A Lead moves an assigned, still-open request to another Coordinator."""
    if event.coordinator_id is None:
        raise ValueError("This request is not assigned yet; assign it instead")
    if event.status not in UNASSIGNED_VISIBLE_STATUSES + ("safety_check", "confirmed"):
        raise ValueError(f"A {event.status.replace('_', ' ')} request cannot be reassigned")
    _require_active_coordinator(new_coordinator)
    if new_coordinator.id == event.coordinator_id:
        raise ValueError("This request is already assigned to that Coordinator")
    if dry_run:
        return event
    previous_coordinator_id = event.coordinator_id
    event = reassign_coordinator(event, new_coordinator, assigned_by_id=assigned_by_id)
    _resolve_pending_request(event, REASSIGNMENT_COMPLETED, assigned_by_id,
                             note=f"Reassigned to {new_coordinator.name}",
                             requested_by=previous_coordinator_id)
    return event


def coordinators_with_workload() -> list[dict]:
    """Active Coordinators with their number of active events (Under Review
    through Confirmed), least busy first — the first entry is the suggestion.
    openRequests is kept as an alias of activeEvents for older clients."""
    coordinators = _active_coordinators()
    counts = dict(
        db.session.query(Event.coordinator_id, func.count(Event.id))
        .filter(Event.status.in_(ACTIVE_ASSIGNED_STATUSES))
        .group_by(Event.coordinator_id)
        .all()
    )
    rows = []
    for c in coordinators:
        active = counts.get(c.id, 0)
        rows.append({"id": c.id, "name": c.name, "activeEvents": active, "openRequests": active})
    return sorted(rows, key=lambda r: (r["activeEvents"], r["id"]))


# Statuses in which an assigned event still needs its Coordinator's attention.
ACTIVE_ASSIGNED_STATUSES = OPEN_STATUSES + ("safety_check", "confirmed")


def supervision_overview() -> list[dict]:
    """Lead supervision view: every active Coordinator with the active events
    currently assigned to them (soonest first). Coordinators with nothing
    assigned are still listed, so the Lead can see who has capacity."""
    coordinators = _active_coordinators()
    events = (
        Event.query.filter(
            Event.coordinator_id.in_([c.id for c in coordinators] or [-1]),
            Event.status.in_(ACTIVE_ASSIGNED_STATUSES),
        )
        .order_by(Event.proposed_date.asc(), Event.id.asc())
        .all()
    )
    by_coordinator = {c.id: [] for c in coordinators}
    for e in events:
        by_coordinator[e.coordinator_id].append({
            "id": e.id,
            "name": e.name,
            "organiserName": e.organiser.name if e.organiser else None,
            "proposedDate": e.proposed_date.isoformat() if e.proposed_date else None,
            "proposedTime": e.proposed_time.strftime("%H:%M") if e.proposed_time else None,
            "expectedAttendance": e.expected_attendance,
            "status": e.status,
            "statusLabel": e.status_label,
        })
    rows = [
        {"id": c.id, "name": c.name, "email": c.email,
         "activeEventCount": len(by_coordinator[c.id]), "events": by_coordinator[c.id]}
        for c in coordinators
    ]
    return sorted(rows, key=lambda r: (r["name"].lower(), r["id"]))


def assignment_history(event: Event) -> list[dict]:
    """Every (re)assignment of this event, oldest first. Never deleted, so a
    reassignment keeps the earlier entries (closed with unassignedAt)."""
    entries = sorted(event.coordinator_history, key=lambda h: (h.assigned_at, h.id))
    return [h.to_dict() for h in entries]


def has_coordinator_history(event: Event, user_id: int) -> bool:
    """True if user_id is or ever was a coordinator on this event (keeps
    previous coordinators' read-only visibility after reassignment)."""
    return any(h.coordinator_id == user_id for h in event.coordinator_history)


# Events can end up with coordinator_id = NULL while already "submitted" if
# no Coordinator was available at auto-assign time (see assign_coordinator's
# ValueError path in submit_event) — so this must be checked in addition to
# OPEN_STATUSES, not just at "under_review" onward.
UNASSIGNED_VISIBLE_STATUSES = ("submitted",) + OPEN_STATUSES


def list_unassigned_events():
    """Events with no assigned Coordinator, surfaced to all Coordinators for
    planning visibility only. There is no self-assign / claim action here —
    reassignment (and initial assignment) is deliberately Coordinator-to-
    Coordinator via assign_coordinator/reassign_coordinator, per Q&A #6/#13/#22."""
    return (
        Event.query.filter(
            Event.coordinator_id.is_(None),
            Event.status.in_(UNASSIGNED_VISIBLE_STATUSES),
        )
        .order_by(Event.proposed_date.asc())
        .all()
    )


def try_assign_and_advance(event: Event) -> Event:
    """Retries automatic assignment for an event that was submitted while no
    Coordinator was available (see review.submit_event) and, on success,
    advances it into under_review the same way a normal submission would.

    get_next_coordinator() still makes the actual pick here — the caller
    (any Coordinator, via the Planning view) only triggers the retry, never
    chooses who receives it. That keeps this consistent with "no manual
    self-assignment and no accept/decline step.\""""
    if event.coordinator_id is not None:
        raise ValueError("This event already has an assigned Coordinator")
    if event.status != "submitted":
        raise ValueError("Only a submitted, unassigned event can be auto-assigned")

    assign_coordinator(event)  # raises ValueError again if still nobody available
    change_status(event, "under_review", changed_by_id=event.coordinator_id)
    return event


def coordinator_calendar(user_id: int):
    """Every event user_id currently coordinates or has ever coordinated.
    Events they no longer own are included read-only (isReadOnly=True) so a
    previous Coordinator keeps visibility after handing an event off."""
    history = (
        EventCoordinatorHistory.query.filter_by(coordinator_id=user_id)
        .order_by(EventCoordinatorHistory.assigned_at.desc())
        .all()
    )

    seen_event_ids = set()
    results = []
    for entry in history:
        if entry.event_id in seen_event_ids:
            continue
        seen_event_ids.add(entry.event_id)
        event = entry.event
        results.append({**event.to_dict(), "isReadOnly": event.coordinator_id != user_id})
    # Events assigned before assignment history was recorded (older data)
    # still belong on the current Coordinator's calendar.
    for event in Event.query.filter(Event.coordinator_id == user_id, Event.status != "draft").all():
        if event.id not in seen_event_ids:
            results.append({**event.to_dict(), "isReadOnly": False})
    return results


# ---------------------------------------------------------------------
# Reassignment requests: Coordinators ask, Leads decide
# ---------------------------------------------------------------------

# Statuses in which an event can still be handed to another Coordinator.
REASSIGNABLE_STATUSES = ACTIVE_ASSIGNED_STATUSES
REASON_MAX_LENGTH = 500


def pending_reassignment_request(event_id: int):
    return (CoordinatorReassignmentRequest.query
            .filter_by(event_id=event_id, status=REASSIGNMENT_PENDING)
            .order_by(CoordinatorReassignmentRequest.id.desc()).first())


def latest_reassignment_request(event_id: int):
    return (CoordinatorReassignmentRequest.query.filter_by(event_id=event_id)
            .order_by(CoordinatorReassignmentRequest.id.desc()).first())


def request_reassignment(event: Event, coordinator_id: int, reason: str):
    """The assigned Coordinator asks the Leads to move the event to someone
    else. They cannot choose the new Coordinator; a Lead does."""
    if event.coordinator_id != coordinator_id:
        raise PermissionError("Only the currently assigned Coordinator can ask for this event to be reassigned")
    if event.status not in REASSIGNABLE_STATUSES:
        raise ValueError(f"A {event.status.replace('_', ' ')} event cannot be reassigned")
    reason = (reason or "").strip()
    validate_descriptive_text(reason, "reason")
    if len(reason) > REASON_MAX_LENGTH:
        raise ValueError(f"Reason must be {REASON_MAX_LENGTH} characters or fewer")
    if pending_reassignment_request(event.id):
        raise ValueError("A reassignment request for this event is already waiting for a Coordinator Lead")

    req = CoordinatorReassignmentRequest(event_id=event.id, requested_by=coordinator_id, reason=reason)
    db.session.add(req)
    db.session.flush()
    notifications.notify_leads_of_reassignment_request(event, req)
    db.session.commit()
    return req


def decline_reassignment_request(event: Event, lead_id: int, note: str = None):
    """A Lead keeps the current Coordinator; the Coordinator is told why."""
    req = pending_reassignment_request(event.id)
    if req is None:
        raise ValueError("There is no pending reassignment request for this event")
    note = (note or "").strip() or None
    if note and len(note) > REASON_MAX_LENGTH:
        raise ValueError(f"Note must be {REASON_MAX_LENGTH} characters or fewer")
    req.status = REASSIGNMENT_DECLINED
    req.decided_by = lead_id
    req.decided_at = utcnow()
    req.decision_note = note
    notifications.notify_coordinator_of_reassignment_decision(event, req)
    db.session.commit()
    return req


def withdraw_reassignment_request(event: Event, coordinator_id: int):
    req = pending_reassignment_request(event.id)
    if req is None:
        raise ValueError("There is no pending reassignment request for this event")
    if req.requested_by != coordinator_id:
        raise PermissionError("Only the Coordinator who asked can withdraw this request")
    req.status = REASSIGNMENT_WITHDRAWN
    req.decided_at = utcnow()
    notifications.clear_reassignment_request_notices(event, {"outcome": "withdrawn"})
    db.session.commit()
    return req


def _resolve_pending_request(event: Event, status: str, decided_by: int = None, note: str = None,
                             requested_by: int = None, commit: bool = True):
    """Closes the event's pending request (if any) once it no longer needs a
    decision. requested_by limits it to that Coordinator's request."""
    req = pending_reassignment_request(event.id)
    if req is None or (requested_by is not None and req.requested_by != requested_by):
        return None
    req.status = status
    req.decided_by = decided_by
    req.decided_at = utcnow()
    req.decision_note = note
    notifications.clear_reassignment_request_notices(event, {"outcome": status})
    if commit:
        db.session.commit()
    return req


def close_reassignment_request_for_closed_event(event: Event):
    """Called (inside the status change, which commits) when an event is
    cancelled, rejected or completed: nobody needs to act on it any more."""
    return _resolve_pending_request(event, REASSIGNMENT_CLOSED, note=f"Event {event.status}", commit=False)


def pending_reassignment_requests() -> list[dict]:
    """Every pending request, oldest first, for the Leads' Assignment Queue."""
    rows = (CoordinatorReassignmentRequest.query.filter_by(status=REASSIGNMENT_PENDING)
            .order_by(CoordinatorReassignmentRequest.created_at.asc()).all())
    return [r.to_dict() for r in rows]
