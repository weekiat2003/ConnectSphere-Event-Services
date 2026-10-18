"""
Equipment Availability Checking / Equipment Reservation models.

EventEquipmentRequirement (in app/models/event.py) already captures what an
Organiser asked for when creating an event request -- that model is NOT
touched here. These models add the separate concepts of a real inventory
catalogue (what ConnectSphere actually owns) and reservations against it,
matched to a requirement by equipment_type/name (no FK needed on the
existing table, so event.py stays untouched).
"""
from app.common.time import utcnow
from app.extensions import db


class EquipmentItem(db.Model):
    """Technical Support Staff's inventory catalogue."""
    __tablename__ = "equipment_items"

    id = db.Column(db.BigInteger, primary_key=True)
    name = db.Column(db.String(150), unique=True, nullable=False)
    category = db.Column(db.String(100), nullable=True)
    total_quantity = db.Column(db.Integer, nullable=False, default=0)
    status = db.Column(db.String(20), nullable=False, default="active")
    # active | maintenance | retired
    created_at = db.Column(db.DateTime, default=utcnow)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "category": self.category,
            "totalQuantity": self.total_quantity,
            "status": self.status,
        }


class EquipmentReservation(db.Model):
    """Equipment Reservation epic. Links an event's requested equipment
    (by name match against EventEquipmentRequirement.equipment_type) to a
    real EquipmentItem, for a specific date/time window."""
    __tablename__ = "equipment_reservations"

    id = db.Column(db.BigInteger, primary_key=True)
    event_id = db.Column(db.BigInteger, db.ForeignKey("events.id", ondelete="CASCADE"), nullable=False)
    equipment_requirement_id = db.Column(
        db.BigInteger, db.ForeignKey("event_equipment_requirements.id", ondelete="SET NULL"), nullable=True
    )
    equipment_item_id = db.Column(db.BigInteger, db.ForeignKey("equipment_items.id"), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    start_datetime = db.Column(db.DateTime, nullable=False)
    end_datetime = db.Column(db.DateTime, nullable=False)
    status = db.Column(db.String(20), nullable=False, default="reserved")
    # reserved | released
    created_by = db.Column(db.BigInteger, db.ForeignKey("users.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=utcnow)
    event = db.relationship("Event", backref="equipment_reservations")
    
    def to_dict(self):
        return {
            "id": self.id,
            "eventId": self.event_id,
            "equipmentItemId": self.equipment_item_id,
            "quantity": self.quantity,
            "start": self.start_datetime.isoformat(),
            "end": self.end_datetime.isoformat(),
            "status": self.status,
        }
