from app.common.time import utcnow
from app.extensions import db


class ChangeRequest(db.Model):
    __tablename__ = "change_requests"

    id = db.Column(db.BigInteger, primary_key=True)
    event_id = db.Column(db.BigInteger, db.ForeignKey("events.id", ondelete="CASCADE"), nullable=False)
    organiser_id = db.Column(db.BigInteger, db.ForeignKey("users.id"), nullable=False)
    request_type = db.Column(db.String(20), nullable=False, default="change")
    requested_changes = db.Column(db.JSON, nullable=False)
    reason = db.Column(db.Text, nullable=False)
    is_significant = db.Column(db.Boolean, nullable=False, default=False)

    # pending | re_review | processed | rejected
    status = db.Column(db.String(30), nullable=False, default="pending")

    coordinator_id = db.Column(db.BigInteger, db.ForeignKey("users.id"), nullable=True)
    decision_reason = db.Column(db.Text, nullable=True)
    decided_at = db.Column(db.DateTime, nullable=True)

    # Who triggered re-review, and when. The request remains unresolved while
    # it is under re-review.
    re_review_by = db.Column(db.BigInteger, db.ForeignKey("users.id"), nullable=True)
    re_review_at = db.Column(db.DateTime, nullable=True)

    created_at = db.Column(db.DateTime, default=utcnow)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "eventId": self.event_id,
            "organiserId": self.organiser_id,
            "requestType": self.request_type,
            "status": self.status,
            "isSignificant": self.is_significant,
            "requestedChanges": self.requested_changes or {},
            "reason": self.reason,
            "decisionReason": self.decision_reason,
            "decidedAt": self.decided_at.isoformat() if self.decided_at else None,
            "reReviewBy": self.re_review_by,
            "reReviewAt": self.re_review_at.isoformat() if self.re_review_at else None,
            "createdAt": self.created_at.isoformat() if self.created_at else None,
            "coordinatorId": self.coordinator_id,
        }


class ArrangementFlag(db.Model):
    """A venue booking, equipment reservation/requirement, or registration that
    needs reconsideration because a significant proposed change may affect it."""

    __tablename__ = "arrangement_flags"

    id = db.Column(db.BigInteger, primary_key=True)
    event_id = db.Column(db.BigInteger, db.ForeignKey("events.id", ondelete="CASCADE"), nullable=False)
    change_request_id = db.Column(
        db.BigInteger,
        db.ForeignKey("change_requests.id", ondelete="CASCADE"),
        nullable=False,
    )

    # venue_booking | equipment | registration
    kind = db.Column(db.String(30), nullable=False)
    target_id = db.Column(db.BigInteger, nullable=False)
    reason = db.Column(db.String(255), nullable=False, default="Needs reconsideration")

    created_at = db.Column(db.DateTime, default=utcnow)
    cleared_at = db.Column(db.DateTime, nullable=True)
    
class EventChangeHistory(db.Model):
    """One row per field changed when a Coordinator processes a change request."""

    __tablename__ = "event_change_history"

    id = db.Column(db.BigInteger, primary_key=True)
    event_id = db.Column(db.BigInteger, db.ForeignKey("events.id", ondelete="CASCADE"), nullable=False)
    change_request_id = db.Column(
        db.BigInteger, db.ForeignKey("change_requests.id", ondelete="CASCADE"), nullable=False
    )
    field = db.Column(db.String(100), nullable=False)
    old_value = db.Column(db.JSON, nullable=True)
    new_value = db.Column(db.JSON, nullable=True)
    changed_by = db.Column(db.BigInteger, db.ForeignKey("users.id"), nullable=False)
    changed_at = db.Column(db.DateTime, default=utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "eventId": self.event_id,
            "changeRequestId": self.change_request_id,
            "field": self.field,
            "oldValue": self.old_value,
            "newValue": self.new_value,
            "changedBy": self.changed_by,
            "changedAt": self.changed_at.isoformat() if self.changed_at else None,
        }