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
from app.models.event import Event, EventCoordinatorHistory
from app.models.user import Role, User

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


def assign_coordinator(event: Event, coordinator: User = None, assignment_type: str = "auto") -> Event:
    coordinator = coordinator or get_next_coordinator()
    if coordinator is None:
        raise ValueError("No active Event Coordinator is available for assignment")

    event.coordinator_id = coordinator.id
    db.session.add(
        EventCoordinatorHistory(
            event_id=event.id,
            coordinator_id=coordinator.id,
            assignment_type=assignment_type,
        )
    )
    db.session.commit()
    return event


def reassign_coordinator(event: Event, new_coordinator: User) -> Event:
    """Reassignment is agreed offline between coordinators; this records the
    handover once that agreement has been made (per Q&A #6/#13/#22)."""
    open_entry = (
        EventCoordinatorHistory.query.filter_by(
            event_id=event.id, coordinator_id=event.coordinator_id, unassigned_at=None
        ).first()
    )
    if open_entry:
        open_entry.unassigned_at = utcnow()

    return assign_coordinator(event, coordinator=new_coordinator, assignment_type="reassignment")


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
    return results
