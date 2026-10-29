"""Attendee Registration: capacity, waiting list, withdrawals and the Organiser's
open/close switch. Routes stay thin; every rule lives here.

Concurrency: every change takes a row lock on the event (`SELECT ... FOR UPDATE`,
a no-op on SQLite), so two Attendees racing for the last place are processed one
after the other: the first is registered, the second is told the event is full.
The unique key on `registrations` stops duplicate active records even if a lock
were ever skipped.
"""
from datetime import datetime, time

from sqlalchemy import func

from app.common.time import utcnow
from app.extensions import db
from app.models.event import Event
from app.models.registration import (
    ACTIVE_STATUSES,
    REG_REGISTERED,
    REG_WAITLISTED,
    REG_WITHDRAWN,
    EventRegistrationSetting,
    EventUpdateSubscription,
    Registration,
)
from app.notifications.services import triggers as notifications
from app.models.venue import BOOKING_APPROVED, Venue, VenueBooking

STATUS_CONFIRMED = "confirmed"
FINISHED_STATUSES = ("completed", "cancelled")
# Attendees can only ever see events in these states (anything else is "not found").
PUBLIC_STATUSES = (STATUS_CONFIRMED, "completed", "cancelled")
MAX_PAGE_SIZE = 100


class RegistrationError(Exception):
    status_code = 400
    code = "error"

    def __init__(self, message, code=None):
        super().__init__(message)
        if code:
            self.code = code


class NotFound(RegistrationError):
    status_code = 404
    code = "not_found"


class Forbidden(RegistrationError):
    status_code = 403
    code = "forbidden"


class Conflict(RegistrationError):
    status_code = 409
    code = "conflict"


class EventFull(Conflict):
    code = "event_full"


# ----------------------------------------------------------------- helpers
def _capacity(event):
    """Intended capacity set by the Organiser; None means unlimited."""
    cap = event.intended_capacity
    return cap if cap and cap > 0 else None


def _lock_event(event_id):
    return db.session.query(Event).filter(Event.id == event_id).with_for_update().first()


def _public_event(event_id):
    """The event if an Attendee may know it exists, else NotFound (never reveals more)."""
    event = db.session.get(Event, event_id)
    if event is None or event.status not in PUBLIC_STATUSES or not event.registration_required:
        raise NotFound("Event not found")
    return event


def _lock_public_event(event_id):
    _public_event(event_id)
    return _lock_event(event_id)


def _counts(event_id):
    rows = (
        db.session.query(Registration.status, func.count(Registration.id))
        .filter(Registration.event_id == event_id)
        .group_by(Registration.status)
        .all()
    )
    found = dict(rows)
    return {
        REG_REGISTERED: found.get(REG_REGISTERED, 0),
        REG_WAITLISTED: found.get(REG_WAITLISTED, 0),
        REG_WITHDRAWN: found.get(REG_WITHDRAWN, 0),
    }


def _is_open(event):
    setting = db.session.get(EventRegistrationSetting, event.id)
    return bool(setting and setting.is_open and event.status == STATUS_CONFIRMED)


def _event_start(event):
    if event.proposed_date is None:
        return None
    return datetime.combine(event.proposed_date, event.proposed_time or time.min)


def _has_started(event):
    start = _event_start(event)
    return start is not None and start <= utcnow()


def _active_registration(event_id, attendee_id):
    return Registration.query.filter(
        Registration.event_id == event_id,
        Registration.attendee_id == attendee_id,
        Registration.status.in_(ACTIVE_STATUSES),
    ).first()


def queue_position(registration):
    """1 = next in line. Order is the row id, i.e. the order requests arrived."""
    if registration.status != REG_WAITLISTED:
        return None
    ahead = Registration.query.filter(
        Registration.event_id == registration.event_id,
        Registration.status == REG_WAITLISTED,
        Registration.id < registration.id,
    ).count()
    return ahead + 1


def rebalance(event):
    """Move waitlisted Attendees to registered, in queue order, while places are free.
    Covers withdrawals and an Organiser raising the capacity. Returns who was promoted."""
    counts = _counts(event.id)
    cap = _capacity(event)
    free = counts[REG_WAITLISTED] if cap is None else max(0, cap - counts[REG_REGISTERED])
    if free <= 0 or counts[REG_WAITLISTED] == 0:
        return []
    waiting = (
        Registration.query.filter_by(event_id=event.id, status=REG_WAITLISTED)
        .order_by(Registration.id)
        .limit(free)
        .all()
    )
    for registration in waiting:
        registration.status = REG_REGISTERED
        # ISP-108: only the promoted Attendee(s) hear about it — no one else
        # on the waiting list is notified at this point.
        notifications.notify_attendee_status_change(
            event, registration.attendee_id, REG_WAITLISTED, REG_REGISTERED,
            note="A place became available and it is now yours.",
        )
    db.session.flush()
    return waiting


def _venue_names(event_id):
    rows = (
        db.session.query(Venue.name)
        .join(VenueBooking, VenueBooking.venue_id == Venue.id)
        .filter(VenueBooking.event_id == event_id, VenueBooking.status == BOOKING_APPROVED)
        .distinct()
        .all()
    )
    return sorted(name for (name,) in rows)


def _places(event, counts):
    cap = _capacity(event)
    remaining = None if cap is None else max(0, cap - counts[REG_REGISTERED])
    return cap, remaining


# --------------------------------------------------------- attendee: browse
def event_summary(event, attendee_id=None):
    """Public details only: no coordinator, review comments, equipment or history."""
    counts = _counts(event.id)
    cap, remaining = _places(event, counts)
    open_now = _is_open(event)
    mine = _active_registration(event.id, attendee_id) if attendee_id else None
    return {
        "id": event.id,
        "name": event.name,
        "description": event.description,
        "date": event.proposed_date.isoformat() if event.proposed_date else None,
        "time": event.proposed_time.strftime("%H:%M") if event.proposed_time else None,
        "venues": _venue_names(event.id),
        "status": event.status,
        "statusLabel": event.status.replace("_", " ").capitalize(),
        "registrationOpen": open_now,
        "capacity": cap,
        "placesRemaining": remaining,
        "isFull": remaining == 0,
        "canRegister": open_now and not mine and remaining != 0,
        "canJoinWaitlist": open_now and not mine and remaining == 0,
        "followingUpdates": bool(attendee_id) and _is_following(event.id, attendee_id),
        "myRegistration": (
            {"id": mine.id, "status": mine.status, "queuePosition": queue_position(mine)}
            if mine
            else None
        ),
    }


def list_events(attendee_id):
    """Confirmed events that take registrations (open or not, flagged in each item)."""
    events = (
        Event.query.filter(Event.status == STATUS_CONFIRMED, Event.registration_required.is_(True))
        .order_by(Event.proposed_date, Event.proposed_time, Event.id)
        .all()
    )
    changed = False
    for event in events:
        changed = bool(rebalance(event)) or changed
    if changed:
        db.session.commit()
    return [event_summary(e, attendee_id) for e in events]


def get_event(event_id, attendee_id):
    event = _public_event(event_id)
    if rebalance(event):
        db.session.commit()
    return event_summary(event, attendee_id)


# ------------------------------------------------- attendee: register & wait
def _check_can_take_registrations(event):
    if event.status in FINISHED_STATUSES:
        raise Conflict(
            f"This event is {event.status}, so registration is no longer possible.",
            code="event_finished",
        )
    if event.status != STATUS_CONFIRMED:
        raise NotFound("Event not found")
    if not _is_open(event):
        raise Conflict("Registration is not open for this event.", code="registration_closed")


def _already_active(event_id, attendee_id):
    existing = _active_registration(event_id, attendee_id)
    if existing:
        raise Conflict(
            f"You already have an active registration for this event ({existing.status}).",
            code="already_registered",
        )


def register(event_id, attendee_id):
    event = _lock_public_event(event_id)
    _check_can_take_registrations(event)
    _already_active(event.id, attendee_id)
    rebalance(event)

    cap, remaining = _places(event, _counts(event.id))
    if remaining == 0:
        raise EventFull("This event is full. You can join the waiting list instead.")

    registration = Registration(event_id=event.id, attendee_id=attendee_id, status=REG_REGISTERED)
    db.session.add(registration)
    db.session.commit()
    return registration


def join_waitlist(event_id, attendee_id):
    event = _lock_public_event(event_id)
    _check_can_take_registrations(event)
    _already_active(event.id, attendee_id)
    rebalance(event)

    cap, remaining = _places(event, _counts(event.id))
    if remaining != 0:
        raise Conflict(
            "This event still has places, so you can register directly.",
            code="places_available",
        )

    registration = Registration(event_id=event.id, attendee_id=attendee_id, status=REG_WAITLISTED)
    db.session.add(registration)
    db.session.commit()
    return registration


def withdraw(registration_id, attendee_id):
    """Returns (registration, promoted). Only the owner may withdraw."""
    registration = db.session.get(Registration, registration_id)
    if registration is None:
        raise NotFound("Registration not found")
    if registration.attendee_id != attendee_id:
        raise Forbidden("You can only withdraw your own registration.")

    event = _lock_event(registration.event_id)
    db.session.refresh(registration)
    if registration.status == REG_WITHDRAWN:
        raise Conflict("You have already withdrawn this registration.", code="already_withdrawn")
    if event.status in FINISHED_STATUSES:
        raise Conflict(
            f"This event is {event.status}, so a registration can no longer be withdrawn.",
            code="event_finished",
        )
    if _has_started(event):
        raise Conflict(
            "This event has already started, so a registration can no longer be withdrawn.",
            code="event_started",
        )

    old_status = registration.status
    registration.status = REG_WITHDRAWN
    db.session.flush()
    notifications.notify_attendee_status_change(event, attendee_id, old_status, REG_WITHDRAWN)
    if old_status == REG_WAITLISTED:
        # Everyone behind a departing waiting-list entry moves up one place.
        notifications.notify_waitlist_positions_moved(event, registration.id)
    promoted = rebalance(event)
    db.session.commit()
    return registration, promoted


def my_registrations(attendee_id):
    registrations = (
        Registration.query.filter_by(attendee_id=attendee_id)
        .order_by(Registration.id.desc())
        .all()
    )
    changed = False
    for event_id in {r.event_id for r in registrations if r.status == REG_WAITLISTED}:
        event = db.session.get(Event, event_id)
        changed = bool(event and rebalance(event)) or changed
    if changed:
        db.session.commit()
        for r in registrations:
            db.session.refresh(r)

    result = []
    for r in registrations:
        event = db.session.get(Event, r.event_id)
        result.append(
            {
                **r.to_dict(),
                "queuePosition": queue_position(r),
                "event": {
                    "id": event.id,
                    "name": event.name,
                    "date": event.proposed_date.isoformat() if event.proposed_date else None,
                    "time": event.proposed_time.strftime("%H:%M") if event.proposed_time else None,
                    "status": event.status,
                    "statusLabel": event.status.replace("_", " ").capitalize(),
                }
                if event
                else None,
            }
        )
    return result


# ------------------------------------------------------ organiser / coordinator
def _own_event_or_error(event_id, user_id, organiser_only):
    event = db.session.get(Event, event_id)
    if event is None:
        raise NotFound("Event not found")
    is_organiser = event.organiser_id == user_id
    is_coordinator = event.coordinator_id == user_id
    if not (is_organiser or (is_coordinator and not organiser_only)):
        raise Forbidden("You do not manage this event.")
    return event


def _set_open(event_id, organiser_id, want_open):
    _own_event_or_error(event_id, organiser_id, organiser_only=True)
    event = _lock_event(event_id)
    if not event.registration_required:
        raise Conflict("This event does not take registrations.", code="registration_not_required")

    setting = db.session.get(EventRegistrationSetting, event.id)
    currently_open = bool(setting and setting.is_open)

    if want_open:
        if event.status in FINISHED_STATUSES:
            raise Conflict(
                f"This event is {event.status}, so registration cannot be opened.",
                code="event_finished",
            )
        if event.status != STATUS_CONFIRMED:
            raise Conflict(
                "Registration can only be opened once the event is confirmed.",
                code="event_not_confirmed",
            )
        if currently_open:
            raise Conflict("Registration is already open.", code="already_open")
    elif not currently_open:
        raise Conflict("Registration is already closed.", code="already_closed")

    if setting is None:
        setting = EventRegistrationSetting(event_id=event.id)
        db.session.add(setting)
    setting.is_open = want_open
    if want_open:
        rebalance(event)
    notifications.notify_followers_of_registration_status(event, want_open)
    notifications.notify_organiser_of_registration_status(event, want_open)
    db.session.commit()
    return event


def open_registration(event_id, organiser_id):
    return _set_open(event_id, organiser_id, True)


def close_registration(event_id, organiser_id):
    return _set_open(event_id, organiser_id, False)


def list_managed_events(user_id):
    """Events I organise or coordinate that take registrations (any status, so the
    Organiser can see why an unconfirmed event cannot be opened yet)."""
    events = (
        Event.query.filter(
            Event.registration_required.is_(True),
            (Event.organiser_id == user_id) | (Event.coordinator_id == user_id),
        )
        .order_by(Event.proposed_date, Event.id)
        .all()
    )
    out = []
    for event in events:
        counts = _counts(event.id)
        cap, remaining = _places(event, counts)
        out.append(
            {
                "id": event.id,
                "name": event.name,
                "date": event.proposed_date.isoformat() if event.proposed_date else None,
                "status": event.status,
                "statusLabel": event.status.replace("_", " ").capitalize(),
                "registrationOpen": _is_open(event),
                "isOrganiser": event.organiser_id == user_id,
                "capacity": cap,
                "registered": counts[REG_REGISTERED],
                "waitlisted": counts[REG_WAITLISTED],
                "placesRemaining": remaining,
            }
        )
    return out


def list_attendees(event_id, user_id, page=1, page_size=50):
    """Organiser or assigned Coordinator. Names and statuses only: no credentials or
    unrelated personal data."""
    event = _own_event_or_error(event_id, user_id, organiser_only=False)
    if rebalance(event):
        db.session.commit()

    page = max(1, int(page or 1))
    page_size = min(MAX_PAGE_SIZE, max(1, int(page_size or 50)))

    query = Registration.query.filter_by(event_id=event.id).order_by(Registration.id)
    total = query.count()
    rows = query.offset((page - 1) * page_size).limit(page_size).all()

    counts = _counts(event.id)
    cap, remaining = _places(event, counts)
    return {
        "event": {
            "id": event.id,
            "name": event.name,
            "status": event.status,
            "registrationOpen": _is_open(event),
        },
        "summary": {
            "registered": counts[REG_REGISTERED],
            "waitlisted": counts[REG_WAITLISTED],
            "withdrawn": counts[REG_WITHDRAWN],
            "capacity": cap,
            "placesRemaining": remaining,
        },
        "registrations": [
            {
                "id": r.id,
                "attendeeName": r.attendee.name if r.attendee else None,
                "status": r.status,
                "queuePosition": queue_position(r),
                "registeredAt": r.registered_at.isoformat() if r.registered_at else None,
            }
            for r in rows
        ],
        "page": page,
        "pageSize": page_size,
        "total": total,
        "pages": max(1, -(-total // page_size)),
    }


# ------------------------------------------- attendee: "Notify me" (ISP-108)
def _is_following(event_id, attendee_id):
    return EventUpdateSubscription.query.filter_by(
        event_id=event_id, attendee_id=attendee_id
    ).first() is not None


def set_following(event_id, attendee_id, follow):
    """Opt in to (or out of) updates such as registration opening or closing.
    Idempotent: following twice or unfollowing when not following is fine."""
    event = _public_event(event_id)
    existing = EventUpdateSubscription.query.filter_by(
        event_id=event.id, attendee_id=attendee_id
    ).first()
    if follow and existing is None:
        db.session.add(EventUpdateSubscription(event_id=event.id, attendee_id=attendee_id))
    elif not follow and existing is not None:
        db.session.delete(existing)
    db.session.commit()
    return event_summary(event, attendee_id)
