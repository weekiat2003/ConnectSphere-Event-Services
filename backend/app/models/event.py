from app.common.time import utcnow

from app.extensions import db

created_at = db.Column(db.DateTime, default=utcnow)
updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow)
EVENT_STATUSES = (
    "draft", "submitted", "under_review", "approved",
    "planning", "safety_check", "confirmed", "completed", "cancelled", "rejected",
)
STATUS_LABELS = {s: s.replace("_", " ").capitalize() for s in EVENT_STATUSES}
UNKNOWN_STATUS_LABEL = "Unknown status"

class Event(db.Model):
    __tablename__ = "events"
    __table_args__ = {'extend_existing': True}

    id = db.Column(db.BigInteger, primary_key=True)
    name = db.Column(db.String(255))
    purpose = db.Column(db.String(255))
    description = db.Column(db.Text)
    category = db.Column(db.String(100))

    organiser_id = db.Column(db.BigInteger, db.ForeignKey("users.id"), nullable=False)
    coordinator_id = db.Column(db.BigInteger, db.ForeignKey("users.id"))

    status = db.Column(db.String(20), nullable=False, default="draft")

    proposed_date = db.Column(db.Date)
    proposed_time = db.Column(db.Time)
    expected_attendance = db.Column(db.Integer)

    # venueRequirements
    capacity_needed = db.Column(db.Integer)
    required_layout = db.Column(db.String(100))
    accessibility_needs = db.Column(db.Text)
    required_facilities = db.Column(db.JSON)

    registration_required = db.Column(db.Boolean, default=False)
    intended_capacity = db.Column(db.Integer)

    clarification_flag = db.Column(db.Boolean, default=False)
    clarification_comments = db.Column(db.Text)

    # reviewDecision snapshot (latest decision; full history in EventReview)
    review_outcome = db.Column(db.String(20))
    review_reason = db.Column(db.Text)
    review_timestamp = db.Column(db.DateTime)
    review_coordinator_id = db.Column(db.BigInteger, db.ForeignKey("users.id"))

    resubmitted_from_event_id = db.Column(db.BigInteger, db.ForeignKey("events.id"))

    created_at = db.Column(db.DateTime, default=utcnow())
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow)
    submitted_at = db.Column(db.DateTime)

    equipment_requirements = db.relationship(
        "EventEquipmentRequirement", backref="event", cascade="all, delete-orphan"
    )
    reviews = db.relationship(
        "EventReview",
        foreign_keys="EventReview.event_id",
        backref="event",
        cascade="all, delete-orphan",
    )
    status_history = db.relationship("EventStatusHistory", backref="event", cascade="all, delete-orphan")
    safety_reviews = db.relationship("EventSafetyReview", backref="event", cascade="all, delete-orphan")
    coordinator_history = db.relationship(
        "EventCoordinatorHistory", backref="event", cascade="all, delete-orphan"
    )

    review_coordinator = db.relationship("User", foreign_keys=[review_coordinator_id])
    # Added so list/detail views can show who requested and who's handling an
    # event by name, instead of only a raw id (Coordinator Assignment AC:
    # assigned-requests summary must show the requesting Organiser).
    organiser = db.relationship("User", foreign_keys=[organiser_id])
    coordinator = db.relationship("User", foreign_keys=[coordinator_id])

    clarification_responses = db.relationship(
        "EventClarificationResponse", backref="event", cascade="all, delete-orphan"
    )
    field_edit_logs = db.relationship(
        "EventFieldEditLog", backref="event", cascade="all, delete-orphan"
    )


    @property
    def status_is_valid(self) -> bool:
        return self.status in STATUS_LABELS

    @property
    def status_label(self) -> str:
        return STATUS_LABELS.get(self.status, UNKNOWN_STATUS_LABEL)
    
    def to_dict(self):
        proposed_time = None
        if self.proposed_time is not None:
            proposed_time = self.proposed_time.strftime("%H:%M")

        return {
            "id": self.id,
            "name": self.name,
            "purpose": self.purpose,
            "description": self.description,
            "category": self.category,
            "organiserId": self.organiser_id,
            "organiserName": self.organiser.name if self.organiser else None,
            "coordinatorId": self.coordinator_id,
            "coordinatorName": self.coordinator.name if self.coordinator else None,
            "status": self.status,
            "statusLabel": self.status_label,
            "statusValid": self.status_is_valid,
            "proposedDate": self.proposed_date.isoformat() if self.proposed_date else None,
            "proposedTime": proposed_time,
            "expectedAttendance": self.expected_attendance,
            "venueRequirements": {
                "capacityNeeded": self.capacity_needed,
                "requiredLayout": self.required_layout,
                "accessibilityNeeds": self.accessibility_needs,
                "requiredFacilities": self.required_facilities or [],
            },
            "equipmentRequirements": [e.to_dict() for e in self.equipment_requirements],
            "venueBookings": [booking.to_dict() for booking in self.venue_bookings],
            "registrationRequired": self.registration_required,
            "intendedCapacity": self.intended_capacity,
            "clarificationFlag": self.clarification_flag,
            "clarificationComments": self.clarification_comments,
            "reviewDecision": {
                "outcome": self.review_outcome,
                "reason": self.review_reason,
                "timestamp": self.review_timestamp.isoformat() if self.review_timestamp else None,
                "coordinatorId": self.review_coordinator_id,
                "coordinatorName": self.review_coordinator.name if self.review_coordinator else None,
            },
            "safetyReviews": [review.to_dict() for review in self.safety_reviews],
            "resubmittedFromEventId": self.resubmitted_from_event_id,
            "createdAt": self.created_at.isoformat() if self.created_at else None,
            "updatedAt": self.updated_at.isoformat() if self.updated_at else None,
            "submittedAt": self.submitted_at.isoformat() if self.submitted_at else None,
        }


class EventEquipmentRequirement(db.Model):
    __tablename__ = "event_equipment_requirements"

    id = db.Column(db.BigInteger, primary_key=True)
    event_id = db.Column(db.BigInteger, db.ForeignKey("events.id", ondelete="CASCADE"), nullable=False)
    equipment_type = db.Column(db.String(150), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    technical_notes = db.Column(db.Text)
    status = db.Column(db.String(20), default="requested")
    created_at = db.Column(db.DateTime, default=utcnow())
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow)
    testing_status = db.Column(db.String(20), nullable=False, default="pending")
    installation_status = db.Column(db.String(20), nullable=False, default="pending")
    needs_recheck = db.Column(db.Boolean, nullable=False, default=False)

    def to_dict(self):
        return {
            "id": self.id,
            "type": self.equipment_type,
            "quantity": self.quantity,
            "technicalNotes": self.technical_notes,
            "status": self.status,
            "testingStatus": self.testing_status,
            "installationStatus": self.installation_status,
            "needsRecheck": self.needs_recheck,
            "updatedAt": self.updated_at.isoformat() if self.updated_at else None,
        }


class EventReview(db.Model):
    __tablename__ = "event_reviews"

    id = db.Column(db.BigInteger, primary_key=True)
    event_id = db.Column(db.BigInteger, db.ForeignKey("events.id", ondelete="CASCADE"), nullable=False)
    coordinator_id = db.Column(db.BigInteger, db.ForeignKey("users.id"), nullable=False)
    action = db.Column(db.String(30), nullable=False)
    comments = db.Column(db.Text)
    editable_fields = db.Column(db.JSON, nullable=True)
    withdrawn_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "coordinatorId": self.coordinator_id,
            "action": self.action,
            "comments": self.comments,
            "editableFields": self.editable_fields or [],
            "withdrawnAt": self.withdrawn_at.isoformat() if self.withdrawn_at else None,
            "createdAt": self.created_at.isoformat() if self.created_at else None,
        }

class EventClarificationResponse(db.Model):
    """One organiser response to one clarification request — the 'thread'.
    review_id is UNIQUE: a clarification request can only ever be answered
    once."""

    __tablename__ = "event_clarification_responses"

    id = db.Column(db.BigInteger, primary_key=True)
    event_id = db.Column(db.BigInteger, db.ForeignKey("events.id", ondelete="CASCADE"), nullable=False)
    review_id = db.Column(
        db.BigInteger, db.ForeignKey("event_reviews.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    organiser_id = db.Column(db.BigInteger, db.ForeignKey("users.id"), nullable=False)
    comments = db.Column(db.Text, nullable=False)
    updated_fields = db.Column(db.JSON, nullable=True)
    created_at = db.Column(db.DateTime, default=utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "reviewId": self.review_id,
            "organiserId": self.organiser_id,
            "comments": self.comments,
            "updatedFields": self.updated_fields or {},
            "createdAt": self.created_at.isoformat() if self.created_at else None,
        }

class EventStatusHistory(db.Model):
    __tablename__ = "event_status_history"

    id = db.Column(db.BigInteger, primary_key=True)
    event_id = db.Column(db.BigInteger, db.ForeignKey("events.id", ondelete="CASCADE"), nullable=False)
    old_status = db.Column(db.String(20))
    new_status = db.Column(db.String(20), nullable=False)
    changed_by = db.Column(db.BigInteger, db.ForeignKey("users.id"))
    reason = db.Column(db.Text)
    changed_at = db.Column(db.DateTime, default=utcnow())


class EventSafetyReview(db.Model):
    __tablename__ = "event_safety_reviews"

    id = db.Column(db.BigInteger, primary_key=True)
    event_id = db.Column(db.BigInteger, db.ForeignKey("events.id", ondelete="CASCADE"), nullable=False)
    safety_officer_id = db.Column(db.BigInteger, db.ForeignKey("users.id"), nullable=False)
    decision = db.Column(db.String(30), nullable=False)
    comments = db.Column(db.Text)
    assessed_factors = db.Column(db.JSON, nullable=False, default=list)
    concern_factors = db.Column(db.JSON, nullable=False, default=list)
    affected_arrangements = db.Column(db.JSON, nullable=False, default=list)
    created_at = db.Column(db.DateTime, default=utcnow)

    safety_officer = db.relationship("User", foreign_keys=[safety_officer_id])

    def to_dict(self):
        return {
            "id": self.id,
            "eventId": self.event_id,
            "safetyOfficerId": self.safety_officer_id,
            "safetyOfficerName": self.safety_officer.name if self.safety_officer else None,
            "decision": self.decision,
            "comments": self.comments,
            "assessedFactors": self.assessed_factors,
            "concernFactors": self.concern_factors,
            "affectedArrangements": self.affected_arrangements,
            "createdAt": self.created_at.isoformat() if self.created_at else None,
        }


class EventCoordinatorHistory(db.Model):
    __tablename__ = "event_coordinator_history"

    id = db.Column(db.BigInteger, primary_key=True)
    event_id = db.Column(db.BigInteger, db.ForeignKey("events.id", ondelete="CASCADE"), nullable=False)
    coordinator_id = db.Column(db.BigInteger, db.ForeignKey("users.id"), nullable=False)
    assigned_at = db.Column(db.DateTime, default=utcnow())
    unassigned_at = db.Column(db.DateTime)
    assignment_type = db.Column(db.String(20), default="auto")  # auto | reassignment
class EventFieldEditLog(db.Model):
    """Audit trail for ISP-118 US-1 edits and US-4 lock-rejection attempts."""
    __tablename__ = "event_field_edit_logs"

    id = db.Column(db.BigInteger, primary_key=True)
    event_id = db.Column(db.BigInteger, db.ForeignKey("events.id", ondelete="CASCADE"), nullable=False)
    changed_by = db.Column(db.BigInteger, db.ForeignKey("users.id"), nullable=True)
    fields_changed = db.Column(db.JSON, nullable=False)
    old_values = db.Column(db.JSON, nullable=False)
    new_values = db.Column(db.JSON, nullable=False)
    was_significant = db.Column(db.Boolean, nullable=False, default=False)
    was_rejected = db.Column(db.Boolean, nullable=False, default=False)
    rejection_reason = db.Column(db.String(500), nullable=True)
    created_at = db.Column(db.DateTime, default=utcnow)