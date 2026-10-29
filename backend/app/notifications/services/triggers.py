"""Who gets notified about what: one section per Notification System story.

Every public function here is called from the service that performs the
action (see NOTIFICATIONS.md for the full map). They follow three rules:

  1. Never commit. The calling service commits, so a notification is saved
     if and only if the action it describes is saved.
  2. Never block the action. Outside of tests, a failure while building a
     notification is logged and swallowed (see @_never_blocks). Under
     TESTING it is re-raised so bugs are not hidden.
  3. Every function returns the list of Notification rows it created.

Most event notifications are driven from ONE place: on_event_status_changed(),
which status._record_status_change() calls for every recorded transition. That
keeps the organiser, Lead, Safety Officer, Tech Support and Attendee
notifications consistent with the status history instead of scattering
notify() calls across every service.
"""
from functools import wraps

from flask import current_app

from app.common.time import utcnow
from app.extensions import db
from app.models.event import Event, EventSafetyReview
from app.models.notification import (
    TYPE_COORDINATOR_ASSIGNMENT,
    TYPE_NEW_EQUIPMENT_REQUEST,
    TYPE_NEW_EVENT_SUBMISSION,
    TYPE_NEW_VENUE_BOOKING_REQUEST,
    TYPE_ORGANISER_UPDATE,
    TYPE_REGISTRATION_CHANGE,
    TYPE_SAFETY_CHECK,
    TYPE_VENUE_BOOKING_UPDATE,
)
from app.models.registration import (
    ACTIVE_STATUSES,
    EventUpdateSubscription,
    Registration,
)
from app.models.user import User
from app.models.venue import BOOKING_APPROVED, Venue
from app.notifications.services.core import (
    active_user_ids_with_role,
    clear_notifications,
    notify,
    notify_role,
    notify_users,
)

COORDINATOR_LEAD_ROLE = "event_coordinator_lead"


def _never_blocks(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception:
            if current_app.config.get("TESTING"):
                raise
            current_app.logger.exception("Notification %s failed; action continues", fn.__name__)
            return []

    return wrapper


# ---------------------------------------------------------------------------
# Formatting helpers (kept here so every notification reads the same way)
# ---------------------------------------------------------------------------

def _event_when(event) -> str:
    if event.proposed_date is None:
        return "date to be confirmed"
    text = event.proposed_date.strftime("%d %b %Y").lstrip("0")
    if event.proposed_time is not None:
        text += f", {event.proposed_time.strftime('%H:%M')}"
    return text


def _schedule_text(proposed_date, proposed_time) -> str:
    if proposed_date is None:
        return "no date set"
    text = proposed_date.strftime("%d %b %Y").lstrip("0")
    return text + (f", {proposed_time.strftime('%H:%M')}" if proposed_time else "")


def _timestamp(dt) -> str:
    return dt.strftime("%d %b %Y, %H:%M UTC").lstrip("0") if dt else "just now"


def _name(event) -> str:
    return event.name or f"Event #{event.id}"


def _user_name(user_id) -> str | None:
    user = db.session.get(User, user_id) if user_id else None
    return user.name if user else None


def _booked_venues(event) -> list[str]:
    names = []
    for booking in event.venue_bookings:
        if booking.status == BOOKING_APPROVED:
            venue = db.session.get(Venue, booking.venue_id)
            if venue and venue.name not in names:
                names.append(venue.name)
    return names


def _sentence(text) -> str:
    """User-typed text as a sentence: trimmed, ending in exactly one stop."""
    text = (text or "not given").strip()
    return text if text[-1:] in ".!?" else text + "."


def _humanise(field: str) -> str:
    return field.replace("_", " ").capitalize()


def _event_link(event) -> str:
    return f"/events/{event.id}"


# ===========================================================================
# Status-change dispatcher (called from events/services/status.py)
# ===========================================================================

@_never_blocks
def on_event_status_changed(event, old_status: str, new_status: str,
                            changed_by_id: int = None, reason: str = None) -> list:
    created = []

    if new_status == "submitted":
        created += _organiser(event, "submitted", "Request submitted",
                              f'Your event request "{_name(event)}" was submitted.')
        if event.coordinator_id is None:
            created += notify_coordinator_leads_of_submission(event)


    elif new_status == "approved":
        message = f'"{_name(event)}" was approved by {_user_name(changed_by_id) or "your Coordinator"}.'
        if reason:
            message += f" Comments: {_sentence(reason)}"
        created += _organiser(event, "approved", "Request approved", message)

    elif new_status == "rejected":
        created += _organiser(event, "rejected", "Request rejected",
                              f'"{_name(event)}" was rejected. Reason: {_sentence(reason)}',
                              {"reason": reason})

    elif new_status == "planning" and old_status == "approved":
        created += _organiser(
            event, "planning_started", "Planning has started",
            f'"{_name(event)}" has moved to planning. '
            "The equipment and venue arrangement processes have started.",
        )
        # Planning starts: equipment becomes reservable, so Tech Support acts now.
        if event.equipment_requirements:
            created += notify_tech_support_of_equipment(event, kind="new")

    elif new_status == "planning" and old_status in ("safety_check", "confirmed"):
        created += _organiser(event, "returned_to_planning", "Event returned to planning",
                              f'"{_name(event)}" has returned to planning. Reason: {_sentence(reason)}',
                              {"reason": reason})

    elif new_status == "safety_check":
        created += _organiser(event, "safety_check", "Awaiting safety review",
                              f'All arrangements for "{_name(event)}" are complete. '
                              "It is now awaiting the Safety Officer's review.")
        created += notify_safety_officers_of_safety_check(event)

    elif new_status == "confirmed":
        created += _organiser(event, "confirmed", "Event confirmed",
                              f'"{_name(event)}" passed its safety check and is confirmed.')

    elif new_status == "cancelled":
        created += _organiser(event, "cancelled", "Event cancelled",
                              f'"{_name(event)}" was cancelled. Reason: {_sentence(reason)}',
                              {"reason": reason})
        created += notify_attendees_of_event_cancellation(event, reason)

    elif new_status == "completed":
        created += _organiser(
            event, "completed", "Event completed",
            f'"{_name(event)}" is now over.',
        )

    return created


# ===========================================================================
# ISP-102 — Organiser
# ===========================================================================

def _organiser(event, kind: str, title: str, message: str, extra: dict = None) -> list:
    data = {"kind": kind, **(extra or {})}
    return [notify(event.organiser_id, TYPE_ORGANISER_UPDATE, title, message,
                   event_id=event.id, link=_event_link(event), data=data)]


@_never_blocks
def notify_organiser_of_clarification(event, comments: str, editable_fields: list) -> list:
    fields = [_humanise(f) for f in (editable_fields or [])]
    message = f'Your Coordinator needs clarification on "{_name(event)}": {_sentence(comments)}'
    message += f" You may edit: {', '.join(fields)}." if fields else " No fields are open for editing."
    return _organiser(event, "clarification_requested", "Clarification needed", message,
                      {"comments": comments, "editableFields": list(editable_fields or [])})


@_never_blocks
def notify_organiser_of_safety_decision(event, review: EventSafetyReview) -> list:
    """Rejected / changes requested (approval is covered by the 'confirmed' transition)."""
    label = "rejected" if review.decision == "rejected" else "changes requested"
    affected = review.affected_arrangements or []
    message = (
        f'Safety check {label} for "{_name(event)}". Reason: {_sentence(review.comments)} '
        f"Affected arrangements: {', '.join(affected) or 'none listed'}. "
        "The event has returned to planning."
    )
    return _organiser(event, f"safety_{review.decision}", f"Safety check {label}", message,
                      {"reason": review.comments, "affectedArrangements": affected})


CHANGE_REQUEST_OUTCOMES = {
    "processed": ("Change request applied", "Your change request for \"{name}\" was applied."),
    "applied": ("Change request approved", "Your change request for \"{name}\" is going ahead and has been applied."),
    "re_review": ("Change sent for re-review",
                  "Your change request for \"{name}\" is a significant change and has been sent for re-review."
                  " Affected arrangements will be reconsidered."),
    "rejected": ("Change request rejected", "Your change request for \"{name}\" was rejected. Reason: {reason}"),
}


@_never_blocks
def notify_organiser_of_change_request(event, change_request, outcome: str) -> list:
    """Decision on the organiser's own change request ("necessary update")."""
    title, template = CHANGE_REQUEST_OUTCOMES[outcome]
    is_withdrawal = change_request.request_type == "withdrawal"
    if is_withdrawal:
        title = title.replace("Change request", "Withdrawal request")
        template = template.replace("change request", "withdrawal request")
    message = template.format(name=_name(event), reason=_sentence(change_request.decision_reason))
    return _organiser(event, f"change_request_{outcome}", title, message,
                      {"changeRequestId": change_request.id, "reason": change_request.decision_reason})


def schedule_snapshot(event) -> dict:
    """Take before changing an event; pass to notify_event_details_changed() after."""
    return {
        "date": event.proposed_date,
        "time": event.proposed_time,
        "equipment": _equipment_signature(event),
    }


def _equipment_signature(event):
    return sorted(
        ((r.equipment_type or "").strip().lower(), r.quantity, r.technical_notes or "")
        for r in event.equipment_requirements
    )


@_never_blocks
def notify_event_details_changed(event, before: dict) -> list:
    """Reschedule notice to the organiser (ISP-102 AC7) and changed-equipment
    notice to Tech Support (ISP-106), whichever applies."""
    created = []
    if (before["date"], before["time"]) != (event.proposed_date, event.proposed_time):
        old_text = _schedule_text(before["date"], before["time"])
        new_text = _schedule_text(event.proposed_date, event.proposed_time)
        created += _organiser(
            event, "rescheduled", "Event rescheduled",
            f'"{_name(event)}" has moved from {old_text} to {new_text}.',
            {"previous": old_text, "new": new_text},
        )
    if before["equipment"] != _equipment_signature(event) and event.status in (
        "approved", "planning", "safety_check", "confirmed"
    ):
        created += notify_tech_support_of_equipment(event, kind="updated")
    return created

def notify_organiser_assigned(event, coordinator):
    """Tell the Organiser their request was assigned and moved Submitted -> Under review."""
    core.notify(
        event.organiser_id,
        TYPE_ORGANISER_UPDATE,
        "Request assigned to a coordinator",
        (
            f'Your request "{event.name}" has been assigned to {coordinator.name}. '
            "Its status has changed from Submitted to Under review."
        ),
        event_id=event.id,
        link=f"/events/{event.id}",
        data={
            "kind": "assigned_to_coordinator",
            "coordinatorId": coordinator.id,
            "coordinatorName": coordinator.name,
            "oldStatus": "submitted",
            "newStatus": "under_review",
        },
    )


# ===========================================================================
# ISP-103 — Event Coordinator Lead
# ===========================================================================

def notify_coordinator_leads_of_submission(event) -> list:
    requester = event.organiser.name if event.organiser else "Unknown requester"
    submitted = _timestamp(event.submitted_at)
    data = {
        "requestId": event.id,
        "title": _name(event),
        "requesterName": requester,
        "eventType": event.category,
        "eventDate": _event_when(event),
        "submittedAt": event.submitted_at.isoformat() if event.submitted_at else None,
    }
    message = (
        f'Request #{event.id} "{_name(event)}" from {requester} is waiting in the Unassigned queue. '
        f"Type: {event.category or 'not specified'}. Event date: {_event_when(event)}. "
        f"Submitted {submitted}."
    )
    return notify_role(COORDINATOR_LEAD_ROLE, TYPE_NEW_EVENT_SUBMISSION,
                       "New request awaiting assignment", message,
                       event_id=event.id, link=f"/assignments?event={event.id}", data=data)


# ===========================================================================
# ISP-105 — Coordinator (assignment, reassignment, venue booking updates)
# ===========================================================================

@_never_blocks
def notify_coordinator_assignment(event, coordinator, previous_coordinator_id: int = None) -> list:
    requester = event.organiser.name if event.organiser else "Unknown requester"
    data = {
        "kind": "reassigned" if previous_coordinator_id else "assigned",
        "requestId": event.id,
        "eventName": _name(event),
        "eventDate": _event_when(event),
        "requesterName": requester,
    }
    created = [notify(
        coordinator.id, TYPE_COORDINATOR_ASSIGNMENT, "New event assigned to you",
        f'Request #{event.id} "{_name(event)}" from {requester} '
        f"(event date: {_event_when(event)}) is now assigned to you.",
        event_id=event.id, link=_event_link(event), data=data,
    )]
    if previous_coordinator_id and previous_coordinator_id != coordinator.id:
        created.append(notify(
            previous_coordinator_id, TYPE_COORDINATOR_ASSIGNMENT, "Event reassigned away from you",
            f'Request #{event.id} "{_name(event)}" has been reassigned to {coordinator.name}. '
            "You keep read-only access.",
            event_id=event.id, link=_event_link(event),
            data={**data, "kind": "removed", "newCoordinatorName": coordinator.name},
        ))
    # The organiser learns who is now handling their request.
    if previous_coordinator_id and previous_coordinator_id != coordinator.id:
        created += _organiser(
            event, "coordinator_reassigned", "New Coordinator for your request",
            f'"{_name(event)}" has been reassigned. {coordinator.name} is now your Event Coordinator.',
            {"coordinatorName": coordinator.name,
             "previousCoordinatorName": _user_name(previous_coordinator_id)},
        )
    else:
        created += _organiser(
            event, "coordinator_assigned", "Coordinator assigned",
            f'{coordinator.name} has been assigned as the Event Coordinator for "{_name(event)}".',
            {"coordinatorName": coordinator.name},
        )
    # Other Leads' "awaiting assignment" notices no longer need action (ISP-103 AC5).
    clear_notifications(TYPE_NEW_EVENT_SUBMISSION, event.id,
                        {"assignedTo": coordinator.name, "assignedToId": coordinator.id})
    return created


BOOKING_UPDATE_TITLES = {
    "approved": "Venue booking approved",
    "rejected": "Venue booking rejected",
    "held": "Venue tentatively held",
    "hold_extended": "Venue hold extended",
    "released": "Venue hold released",
    "expired": "Venue hold expired",
    "cancelled": "Venue booking cancelled",
}


@_never_blocks
def notify_coordinator_of_booking_update(booking, change: str, reason: str = None) -> list:
    event = booking.event or db.session.get(Event, booking.event_id)
    venue = db.session.get(Venue, booking.venue_id)
    venue_name = venue.name if venue else f"Venue #{booking.venue_id}"
    message = (
        f'{BOOKING_UPDATE_TITLES[change]}: {venue_name} for "{_name(event)}" '
        f"({_timestamp(booking.start_datetime).replace(' UTC', '')})."
    )
    if reason:
        message += f" Reason: {_sentence(reason)}"
    current = event.coordinator_id if event else None
    recipients = [current] if current else [booking.requested_by]
    return notify_users(recipients, TYPE_VENUE_BOOKING_UPDATE, BOOKING_UPDATE_TITLES[change], message,
                        event_id=booking.event_id, link=_event_link(event) if event else None,
                        data={"bookingId": booking.id, "change": change, "venueName": venue_name})


# ===========================================================================
# ISP-104 — Venue Staff
# ===========================================================================

@_never_blocks
def notify_venue_staff_of_booking_requests(bookings) -> list:
    """One notification per booking, to the Venue Staff member who manages that
    venue (venues.created_by — the only person allowed to approve it). If that
    person is missing or no longer active Venue Staff, all Venue Staff are told
    so the request is not lost."""
    created = []
    venue_staff_ids = set(active_user_ids_with_role("venue_staff"))
    for booking in bookings:
        venue = db.session.get(Venue, booking.venue_id)
        event = booking.event or db.session.get(Event, booking.event_id)
        manager_id = venue.created_by if venue else None
        recipients = [manager_id] if manager_id in venue_staff_ids else []
        venue_name = venue.name if venue else f"Venue #{booking.venue_id}"
        booking_date = (
            booking.start_datetime.strftime("%d %b %Y, %H:%M").lstrip("0")
            if booking.start_datetime else "date not set"
        )
        created += notify_users(
            recipients, TYPE_NEW_VENUE_BOOKING_REQUEST, "New venue booking request",
            f'"{_name(event)}" has requested {venue_name} on {booking_date}.',
            event_id=booking.event_id, link=f"/venues/approval?booking={booking.id}",
            data={"bookingId": booking.id, "venueName": venue_name,
                  "eventName": _name(event), "bookingDate": booking_date},
        )
    return created


# ===========================================================================
# ISP-106 — Technical Support Staff
# ===========================================================================

def notify_tech_support_of_equipment(event, kind: str = "new") -> list:
    items = sorted(event.equipment_requirements, key=lambda r: r.id or 0)
    summary = ", ".join(f"{r.quantity} × {r.equipment_type}" for r in items) or "all equipment removed"
    venues = ", ".join(_booked_venues(event)) or "venue not yet booked"
    requester = event.organiser.name if event.organiser else "Unknown requester"
    if kind == "new":
        title = "New equipment requirements"
        when_text = f"submitted {_timestamp(event.submitted_at)}"
        action = ""
    else:
        title = "Equipment requirements updated"
        when_text = f"updated {_timestamp(utcnow())}"
        action = " Please re-check suitability."
    message = (
        f'"{_name(event)}" — {_event_when(event)}, {venues}. Requested by {requester}, '
        f"{when_text}. Equipment: {summary}.{action}"
    )
    return notify_role(
        "technical_support_staff", TYPE_NEW_EQUIPMENT_REQUEST, title, message,
        event_id=event.id, link=f"/technical-review?event={event.id}",
        data={"kind": kind, "summary": summary, "venues": venues, "requesterName": requester},
    )


# ===========================================================================
# ISP-130 — Safety Officer
# ===========================================================================

def notify_safety_officers_of_safety_check(event) -> list:
    """One per active Safety Officer (notify_users de-duplicates, so a user with
    several roles still gets exactly one). Re-entry after rework is flagged."""
    recheck = (
        db.session.query(EventSafetyReview.id)
        .filter(EventSafetyReview.event_id == event.id)
        .first()
        is not None
    )

    venues = ", ".join(_booked_venues(event)) or "no venue recorded"
    attendance = event.expected_attendance if event.expected_attendance is not None else "not given"
    title = "Safety re-check required" if recheck else "Safety check required"
    message = (
        f'"{_name(event)}" — {_event_when(event)}, {venues}. Expected attendance: {attendance}.'
    )
    if recheck:
        message = "Re-check required. " + message
    return notify_role(
        "safety_officer", TYPE_SAFETY_CHECK, title, message,
        event_id=event.id, link=f"/safety-reviews/{event.id}",
        data={"recheck": recheck, "venues": venues, "expectedAttendance": event.expected_attendance},
    )


# ===========================================================================
# ISP-108 — Attendees
# ===========================================================================

STATUS_LABELS = {
    "registered": "Registered",
    "waitlisted": "Waiting list",
    "withdrawn": "Withdrawn",
    "cancelled": "Cancelled",
}


def _attendee_link(event) -> str:
    return f"/attendee/events/{event.id}"


@_never_blocks
def notify_followers_of_registration_status(event, is_open: bool) -> list:
    follower_ids = [
        s.attendee_id
        for s in EventUpdateSubscription.query.filter_by(event_id=event.id).order_by(EventUpdateSubscription.id)
    ]
    state = "open" if is_open else "closed"
    return notify_users(
        follower_ids, TYPE_REGISTRATION_CHANGE, f"Registration {state}",
        f'Registration for "{_name(event)}" is now {state}.',
        event_id=event.id, link=_attendee_link(event),
        data={"kind": f"registration_{state}", "registrationOpen": is_open},
    )


@_never_blocks
def notify_attendee_status_change(event, attendee_id: int, old_status: str, new_status: str,
                                  note: str = None) -> list:
    old_label = STATUS_LABELS.get(old_status, old_status)
    new_label = STATUS_LABELS.get(new_status, new_status)
    title = "A place is available for you" if (old_status, new_status) == ("waitlisted", "registered") \
        else "Registration status changed"
    message = f'"{_name(event)}": your status changed from {old_label} to {new_label}.'
    if note:
        message += f" {note}"
    return [notify(attendee_id, TYPE_REGISTRATION_CHANGE, title, message,
                   event_id=event.id, link=_attendee_link(event),
                   data={"kind": "status_changed", "oldStatus": old_status, "newStatus": new_status})]


@_never_blocks
def notify_waitlist_positions_moved(event, withdrawn_registration_id: int) -> list:
    """Someone on the waiting list left: everyone behind them moved up by one."""
    behind = (
        Registration.query
        .filter(Registration.event_id == event.id,
                Registration.status == "waitlisted",
                Registration.id > withdrawn_registration_id)
        .order_by(Registration.id)
        .all()
    )
    ahead = Registration.query.filter(
        Registration.event_id == event.id,
        Registration.status == "waitlisted",
        Registration.id < withdrawn_registration_id,
    ).count()
    created = []
    for offset, registration in enumerate(behind):
        new_position = ahead + offset + 1
        created.append(notify(
            registration.attendee_id, TYPE_REGISTRATION_CHANGE, "Waiting-list position changed",
            f'"{_name(event)}": your waiting-list position moved from {new_position + 1} to {new_position}.',
            event_id=event.id, link=_attendee_link(event),
            data={"kind": "position_changed", "oldStatus": "waitlisted", "newStatus": "waitlisted",
                  "oldPosition": new_position + 1, "newPosition": new_position},
        ))
    return created

@_never_blocks
def notify_organiser_of_registration_status(event, is_open: bool) -> list:
    state = "opened" if is_open else "closed"
    return _organiser(
        event, f"registration_{state}", f"Registration {state}",
        f'Registration for "{_name(event)}" has been {state}.',
        {"registrationOpen": is_open},
    )


def notify_attendees_of_event_cancellation(event, reason: str = None) -> list:
    created = []
    active = (
        Registration.query
        .filter(Registration.event_id == event.id, Registration.status.in_(ACTIVE_STATUSES))
        .order_by(Registration.id)
        .all()
    )
    for registration in active:
        created += notify_attendee_status_change(
            event, registration.attendee_id, registration.status, "cancelled",
            note=f"The event was cancelled. Reason: {_sentence(reason)}" if reason else "The event was cancelled.",
        )
    return created
