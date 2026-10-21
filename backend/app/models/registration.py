from app.common.time import utcnow
from app.extensions import db

REG_REGISTERED = "registered"
REG_WAITLISTED = "waitlisted"
REG_WITHDRAWN = "withdrawn"
REGISTRATION_STATUSES = (REG_REGISTERED, REG_WAITLISTED, REG_WITHDRAWN)
ACTIVE_STATUSES = (REG_REGISTERED, REG_WAITLISTED)


class Registration(db.Model):
    """One attendee's place (or waiting-list spot) at an event.

    An attendee can hold only one *active* (registered or waitlisted) record per
    event, but may register again after withdrawing: withdrawn rows are kept as
    history. `active_attendee_id` is NULL for withdrawn rows, so the unique key
    below only constrains the active ones (NULLs never collide).

    Waiting-list order is the row id (first come, first served), so no separate
    position column can ever get out of step.
    """

    __tablename__ = "registrations"
    __table_args__ = (
        db.UniqueConstraint("event_id", "active_attendee_id", name="uq_registration_active"),
        db.Index("idx_reg_event_status", "event_id", "status"),
    )

    id = db.Column(db.BigInteger, primary_key=True)
    event_id = db.Column(
        db.BigInteger, db.ForeignKey("events.id", ondelete="CASCADE"), nullable=False
    )
    attendee_id = db.Column(db.BigInteger, db.ForeignKey("users.id"), nullable=False)
    status = db.Column(db.String(20), nullable=False, default=REG_REGISTERED)
    registered_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=utcnow, onupdate=utcnow)
    active_attendee_id = db.Column(
        db.BigInteger,
        db.Computed("CASE WHEN status <> 'withdrawn' THEN attendee_id END", persisted=True),
    )

    attendee = db.relationship("User", foreign_keys=[attendee_id])

    def to_dict(self):
        return {
            "id": self.id,
            "eventId": self.event_id,
            "attendeeId": self.attendee_id,
            "status": self.status,
            "registeredAt": self.registered_at.isoformat() if self.registered_at else None,
        }


class EventRegistrationSetting(db.Model):
    """Whether the Organiser has opened registration for an event (default: closed)."""

    __tablename__ = "event_registration_settings"

    event_id = db.Column(
        db.BigInteger, db.ForeignKey("events.id", ondelete="CASCADE"), primary_key=True
    )
    is_open = db.Column(db.Boolean, nullable=False, default=False)
    updated_at = db.Column(db.DateTime, nullable=False, default=utcnow, onupdate=utcnow)
