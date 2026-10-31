from app.common.time import utcnow
from app.extensions import db

# ---------------------------------------------------------------------------
# Notification types — one per user story. Add new types here (and only here)
# so the frontend and tests can rely on a single list of valid values.
# ---------------------------------------------------------------------------
TYPE_ORGANISER_UPDATE = "organiser_update"                    # ISP-102
TYPE_NEW_EVENT_SUBMISSION = "new_event_submission"            # ISP-103
TYPE_NEW_VENUE_BOOKING_REQUEST = "new_venue_booking_request"  # ISP-104
TYPE_COORDINATOR_ASSIGNMENT = "coordinator_assignment"        # ISP-105
TYPE_VENUE_BOOKING_UPDATE = "venue_booking_update"            # ISP-105 (story narrative)
TYPE_NEW_EQUIPMENT_REQUEST = "new_equipment_request"          # ISP-106
TYPE_REGISTRATION_CHANGE = "registration_change"              # ISP-108
TYPE_SAFETY_CHECK = "safety_check"                            # ISP-130
TYPE_REASSIGNMENT_REQUEST = "reassignment_request"            # Coordinator Assignment

NOTIFICATION_TYPES = (
    TYPE_ORGANISER_UPDATE,
    TYPE_NEW_EVENT_SUBMISSION,
    TYPE_NEW_VENUE_BOOKING_REQUEST,
    TYPE_COORDINATOR_ASSIGNMENT,
    TYPE_VENUE_BOOKING_UPDATE,
    TYPE_NEW_EQUIPMENT_REQUEST,
    TYPE_REGISTRATION_CHANGE,
    TYPE_SAFETY_CHECK,
    TYPE_REASSIGNMENT_REQUEST,
)


class Notification(db.Model):
    """One in-app message for one user.

    A notification sent to "all Venue Staff" is stored as one row per staff
    member, so each person has their own read/unread state.
    """

    __tablename__ = "notifications"
    __table_args__ = (
        db.Index("idx_notif_recipient_read", "recipient_id", "is_read"),
    )

    id = db.Column(db.BigInteger, primary_key=True)
    recipient_id = db.Column(
        db.BigInteger, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    type = db.Column(db.String(50), nullable=False)
    title = db.Column(db.String(255), nullable=False)
    message = db.Column(db.Text, nullable=False)

    # Optional context so the UI can link to the thing the notification is about.
    event_id = db.Column(
        db.BigInteger, db.ForeignKey("events.id", ondelete="CASCADE"), nullable=True
    )
    link = db.Column(db.String(255), nullable=True)  # frontend route, e.g. "/events/12"

    # Structured details for the UI (old/new dates, positions, assignee, ...).
    data = db.Column(db.JSON, nullable=True)

    is_read = db.Column(db.Boolean, nullable=False, default=False)
    read_at = db.Column(db.DateTime, nullable=True)
    # Set when the notification no longer needs action (e.g. another Lead has
    # already assigned the request). Cleared notifications are read, stay
    # viewable, and never count as unread.
    cleared_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)

    event = db.relationship("Event", foreign_keys=[event_id])

    def to_dict(self):
        return {
            "id": self.id,
            "recipientId": self.recipient_id,
            "type": self.type,
            "title": self.title,
            "message": self.message,
            "eventId": self.event_id,
            "eventName": self.event.name if self.event else None,
            "link": self.link,
            "data": self.data or {},
            "isRead": self.is_read,
            "isCleared": self.cleared_at is not None,
            "readAt": self.read_at.isoformat() if self.read_at else None,
            "createdAt": self.created_at.isoformat() if self.created_at else None,
        }
