from unittest.mock import patch
from sqlalchemy.exc import IntegrityError
import pytest
from datetime import datetime, timezone, date, time
from werkzeug.security import generate_password_hash
from app.models.event import Event, EventClarificationResponse, EventEquipmentRequirement, EventReview
from app.events import routes as event_routes
from app.events.routes import _build_display_fields, _require_confirmation  # both pure/stateless, safe to import directly
from app.models.user import Role, User
from app.events.services.review import (
    request_clarification,
    approve_event,
    reject_event,
    get_clarification_thread,
    respond_to_clarification,
    delete_clarification_request,
    resubmit_rejected_event,
    can_be_resubmitted,
    get_full_review_history,
    get_prior_rejection_decisions,
)
from app.events.services.status import change_status
from app.events.services.assignment import (
    assign_coordinator,
    get_next_coordinator,
    lead_assign,
    reassign_coordinator,
)
from app.extensions import db
from app.common.text_validation import validate_descriptive_text

@pytest.fixture(scope="function")
def test_db(app):
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    with app.app_context():
        db.create_all()
        yield db
        db.drop_all()

@pytest.fixture
def event():
    return Event(
        id=1,
        organiser_id=100,
        coordinator_id=200,
        status="under_review",
        name="Annual Tech Conference",
        purpose="Discuss latest tech trends",
        description="A conference for tech enthusiasts",
        proposed_date="2023-12-01",
        proposed_time="10:00",
        expected_attendance=500,
        required_layout="Theater",
        accessibility_needs="Wheelchair access",
        required_facilities="Projector, Microphones",
        registration_required=True,
        review_timestamp=datetime.now(timezone.utc),  # Use timezone-aware datetime
    )

@pytest.fixture
def coordinator():
    return {"id": 200, "role": "event_coordinator"}

@pytest.fixture
def non_coordinator():
    return {"id": 300, "role": "attendee"}

@pytest.fixture
def organiser():
    return {"id": 100, "role": "event_organiser"}


@pytest.fixture
def second_coordinator():
    return {"id": 201, "role": "event_coordinator"}


@pytest.fixture
def two_real_coordinators(app):
    """assign_coordinator/reassign_coordinator query real User/Role rows,
    so unlike the other fixtures here, this one needs actual persisted
    users rather than a plain dict."""
    with app.app_context():
        role = Role.query.filter_by(name="event_coordinator").first()
        user_a = User(
            name="Real Coordinator A",
            email="realcoord.a@test.com",
            password_hash=generate_password_hash("password"),
        )
        user_a.roles = [role]
        user_b = User(
            name="Real Coordinator B",
            email="realcoord.b@test.com",
            password_hash=generate_password_hash("password"),
        )
        user_b.roles = [role]
        db.session.add_all([user_a, user_b])
        db.session.commit()
        return user_a.id, user_b.id

def _persist_event(coordinator_id=None, status="under_review", **overrides):
    """Persists a minimal, valid, submittable Event."""
    values = dict(
        organiser_id=100,
        coordinator_id=coordinator_id,
        status=status,
        name="Resubmission Test Event",
        purpose="Testing resubmission",
        description="Original description.",
        proposed_date=date(2030, 6, 1),
        proposed_time=time(9, 30),
        expected_attendance=80,
        capacity_needed=60,
        required_layout="theatre",
        accessibility_needs="Step-free access",
        registration_required=True,
        intended_capacity=60,
    )
    values.update(overrides)
    event = Event(**values)
    db.session.add(event)
    db.session.commit()
    return event


def _persist_rejected_event(coordinator_id, reason="Insufficient lead time.", **overrides):
    event = _persist_event(coordinator_id=coordinator_id, **overrides)
    reject_event(event, coordinator_id, reason)
    return event


def _resubmit_and_assign(original, data=None):
    """Resubmissions now wait in the Unassigned queue until a Coordinator Lead
    assigns them (Notification System, ISP-103); do that here."""
    resubmission = resubmit_rejected_event(original, original.organiser_id, data or {})
    return lead_assign(resubmission, get_next_coordinator())


def _build_three_generation_chain(coordinator_id):
    """first (rejected) -> second (clarification, then rejected) -> third (under review)"""
    first = _persist_rejected_event(coordinator_id, reason="First rejection reason.")
    second = _resubmit_and_assign(first)
    request_clarification(second, second.coordinator_id, "Please clarify the catering plan.")
    reject_event(second, second.coordinator_id, "Second rejection reason.")
    third = _resubmit_and_assign(second)
    return first, second, third

def test_request_clarification(app, event, coordinator):
    with app.app_context():
        clarification_comment = "Please provide more details about the venue requirements."
        updated_event = request_clarification(event, coordinator["id"], clarification_comment)
        assert updated_event.clarification_flag is True
        assert updated_event.clarification_comments == clarification_comment

def test_clarification_requires_valid_comment(app, event, coordinator):
    with app.app_context():
        with pytest.raises(ValueError, match="Clarification comment must contain descriptive text"):
            request_clarification(event, coordinator["id"], "!!!")

def test_reject_event(app, event, coordinator):
    with app.app_context():
        reason = "The event does not meet the required criteria."
        updated_event = reject_event(event, coordinator["id"], reason)
        assert updated_event.status == "rejected"
        assert updated_event.review_outcome == "rejected"
        assert updated_event.review_reason == reason

def test_invalid_status_for_review(app, event, coordinator):
    with app.app_context():
        event.status = "draft"
        with pytest.raises(ValueError, match="Only a request under review can be approved"):
            approve_event(event, coordinator["id"], comments="Looks good")
        with pytest.raises(ValueError, match="Only a request under review can be rejected"):
            reject_event(event, coordinator["id"], reason="Invalid reason")
        with pytest.raises(ValueError, match="Clarification can only be requested while a request is under review"):
            request_clarification(event, coordinator["id"], "Need more details")


# =======================================================================
# Clarification requests: comment validation and editable-fields grant
# =======================================================================

@pytest.mark.parametrize("invalid_comment", ["!!!", "12345", "@@@###", "-----", "123-456-7890"])
def test_request_clarification_symbols_or_digits_only_is_rejected(app, event, coordinator, invalid_comment):
    with app.app_context():
        with pytest.raises(ValueError, match="Clarification comment must contain descriptive text"):
            request_clarification(event, coordinator["id"], invalid_comment)


def test_request_clarification_word_comment_is_accepted(app, event, coordinator):
    with app.app_context():
        updated = request_clarification(event, coordinator["id"], "Please confirm A/V setup.")
        assert updated.clarification_comments == "Please confirm A/V setup."


def test_request_clarification_only_assigned_coordinator_can_request(app, event, second_coordinator):
    with app.app_context():
        with pytest.raises(PermissionError, match="Only the assigned Coordinator can request clarification"):
            request_clarification(event, second_coordinator["id"], "Trying to clarify someone else's event.")


def test_multiple_clarifications_are_all_recorded_in_order(app, event, coordinator):
    with app.app_context():
        event.proposed_date = date(2023, 12, 1)
        event.proposed_time = time(10, 0)
        db.session.add(event)
        db.session.commit()

        request_clarification(event, coordinator["id"], "First question.")
        request_clarification(event, coordinator["id"], "Second question.")
        request_clarification(event, coordinator["id"], "Third question.")

        clarification_entries = [r for r in event.reviews if r.action == "clarification_requested"]
        assert [r.comments for r in clarification_entries] == [
            "First question.",
            "Second question.",
            "Third question.",
        ]
        assert event.clarification_comments == "Third question."


# =======================================================================
# Approve / Reject: status and ownership rules not covered by the
# existing test_invalid_status_for_review / test_reject_event
# =======================================================================

def test_approve_event_requires_assigned_coordinator(app, event, second_coordinator):
    with app.app_context():
        with pytest.raises(PermissionError, match="Only the assigned Coordinator can approve this request"):
            approve_event(event, second_coordinator["id"])


def test_reject_event_requires_assigned_coordinator(app, event, second_coordinator):
    with app.app_context():
        with pytest.raises(PermissionError, match="Only the assigned Coordinator can reject this request"):
            reject_event(event, second_coordinator["id"], "Not my call")


def test_reject_event_requires_a_reason(app, event, coordinator):
    with app.app_context():
        with pytest.raises(ValueError, match="At least one rejection reason is required"):
            reject_event(event, coordinator["id"], "")


def test_cannot_approve_an_already_approved_event(app, event, coordinator):
    with app.app_context():
        approve_event(event, coordinator["id"])
        with pytest.raises(ValueError, match="Only a request under review can be approved"):
            approve_event(event, coordinator["id"])


def test_cannot_reject_an_already_rejected_event(app, event, coordinator):
    with app.app_context():
        reject_event(event, coordinator["id"], "First rejection")
        with pytest.raises(ValueError, match="Only a request under review can be rejected"):
            reject_event(event, coordinator["id"], "Second attempt")


# =======================================================================
# Organiser's response to clarification
# =======================================================================
@pytest.mark.parametrize("invalid_comment", ["", "   ", "!!!", "12345"])
def test_respond_to_clarification_requires_valid_comment(app, event, coordinator, organiser, invalid_comment):
    with app.app_context():
        event.proposed_date = date(2023, 12, 1)
        event.proposed_time = time(10, 0)
        db.session.add(event)
        db.session.commit()

        request_clarification(event, coordinator["id"], "Please confirm the headcount.")
        review_id = event.reviews[-1].id

        with pytest.raises(ValueError):
            respond_to_clarification(event, organiser["id"], review_id, {"comments": invalid_comment})


def test_respond_to_clarification_cannot_be_submitted_twice_for_same_review(app, event, coordinator, organiser):
    with app.app_context():
        event.proposed_date = date(2023, 12, 1)
        event.proposed_time = time(10, 0)
        db.session.add(event)
        db.session.commit()

        request_clarification(event, coordinator["id"], "Please confirm the headcount.")
        review_id = event.reviews[-1].id

        respond_to_clarification(event, organiser["id"], review_id, {"comments": "Confirmed at 120."})

        with pytest.raises(ValueError, match="already been responded to"):
            respond_to_clarification(event, organiser["id"], review_id, {"comments": "Trying again."})


def test_respond_to_clarification_fails_for_unknown_review_id(app, event, organiser):
    with app.app_context():
        event.proposed_date = date(2023, 12, 1)
        event.proposed_time = time(10, 0)
        db.session.add(event)
        db.session.commit()

        with pytest.raises(ValueError, match="No such clarification request"):
            respond_to_clarification(event, organiser["id"], 999999, {"comments": "Answering nothing."})


def test_respond_to_clarification_fails_for_non_owning_organiser(app, event, coordinator):
    with app.app_context():
        event.proposed_date = date(2023, 12, 1)
        event.proposed_time = time(10, 0)
        db.session.add(event)
        db.session.commit()

        request_clarification(event, coordinator["id"], "Please confirm the headcount.")
        review_id = event.reviews[-1].id

        with pytest.raises(PermissionError, match="Only the requesting Organiser can respond"):
            respond_to_clarification(event, 999, review_id, {"comments": "Not my event."})


def test_earlier_clarification_remains_answerable_after_a_newer_one_is_opened(app, event, coordinator, organiser):
    with app.app_context():
        event.proposed_date = date(2023, 12, 1)
        event.proposed_time = time(10, 0)
        db.session.add(event)
        db.session.commit()

        request_clarification(event, coordinator["id"], "First question.")
        request_clarification(event, coordinator["id"], "Second question.")
        first_review_id, second_review_id = [r.id for r in event.reviews if r.action == "clarification_requested"]

        respond_to_clarification(event, organiser["id"], second_review_id, {"comments": "Answering the second."})
        assert event.clarification_flag is True

        respond_to_clarification(event, organiser["id"], first_review_id, {"comments": "Answering the first."})
        assert event.clarification_flag is False

        responses = {r.review_id: r.comments for r in EventClarificationResponse.query.filter_by(event_id=event.id)}
        assert responses[first_review_id] == "Answering the first."
        assert responses[second_review_id] == "Answering the second."


def test_get_clarification_thread_pairs_requests_with_responses(app, event, coordinator, organiser):
    with app.app_context():
        event.proposed_date = date(2023, 12, 1)
        event.proposed_time = time(10, 0)
        db.session.add(event)
        db.session.commit()

        request_clarification(event, coordinator["id"], "Still waiting on this one.")
        thread = get_clarification_thread(event)
        assert len(thread) == 1
        assert thread[0]["response"] is None

        review_id = thread[0]["reviewId"]
        respond_to_clarification(event, organiser["id"], review_id, {"comments": "Here is the answer."})

        thread = get_clarification_thread(event)
        assert thread[0]["response"]["comments"] == "Here is the answer."


# =======================================================================
# Review-detail display fields (pure/stateless — no persistence needed)
# =======================================================================

def test_display_fields_show_nil_for_missing_optional_values(app):
    with app.app_context():
        minimal_event = Event(
            organiser_id=100,
            status="under_review",
            name="Minimal Event",
            purpose="Testing",
            description="Only the required fields are set.",
            proposed_date=date(2026, 12, 1),
            expected_attendance=50,
        )
        fields = {f["title"]: f["value"] for f in _build_display_fields(minimal_event)}

        assert fields["Proposed date and time"] == "2026-12-01"
        assert fields["Venue requirements"] == "NIL"
        assert fields["Accessibility requirements"] == "NIL"
        assert fields["Equipment requirements"] == "NIL"
        assert fields["Registration requirements"] == "NIL"


def test_display_fields_show_populated_values_with_exact_titles(app):
    with app.app_context():
        full_event = Event(
            organiser_id=100,
            status="under_review",
            name="Full Event",
            purpose="Testing",
            description="Every optional field is set.",
            proposed_date=date(2026, 12, 1),
            proposed_time=time(9, 30),
            expected_attendance=100,
            capacity_needed=80,
            required_layout="theatre",
            accessibility_needs="Wheelchair access required",
            registration_required=True,
            intended_capacity=80,
        )
        fields = {f["title"]: f["value"] for f in _build_display_fields(full_event)}

        assert fields["Proposed date and time"] == "2026-12-01 09:30:00"
        assert fields["Venue requirements"] == {
            "capacityNeeded": 80,
            "requiredLayout": "theatre",
            "requiredFacilities": "NIL",
        }
        assert fields["Accessibility requirements"] == "Wheelchair access required"
        assert fields["Registration requirements"] == {"registrationRequired": True, "intendedCapacity": 80}


# =======================================================================
# Coordinator assignment / reassignment (needs real User/Role rows)
# =======================================================================

def test_assign_coordinator_picks_an_active_coordinator(app, two_real_coordinators):
    with app.app_context():
        coordinator_a_id, coordinator_b_id = two_real_coordinators
        new_event = Event(
            organiser_id=100,
            status="submitted",
            name="Board Meeting",
            purpose="Quarterly review",
            description="Standard quarterly board meeting.",
            proposed_date=date(2026, 6, 1),
            expected_attendance=20,
        )
        db.session.add(new_event)
        db.session.commit()

        assign_coordinator(new_event)
        assert new_event.coordinator_id in (coordinator_a_id, coordinator_b_id)


def test_reassign_coordinator_updates_assignment_and_history(app, two_real_coordinators):
    with app.app_context():
        coordinator_a_id, coordinator_b_id = two_real_coordinators
        new_event = Event(
            organiser_id=100,
            status="submitted",
            name="Board Meeting",
            purpose="Quarterly review",
            description="Standard quarterly board meeting.",
            proposed_date=date(2026, 6, 1),
            expected_attendance=20,
        )
        db.session.add(new_event)
        db.session.commit()

        assign_coordinator(new_event, coordinator=User.query.get(coordinator_a_id))
        reassign_coordinator(new_event, User.query.get(coordinator_b_id))

        assert new_event.coordinator_id == coordinator_b_id
        history_ids = [h.coordinator_id for h in new_event.coordinator_history]
        assert coordinator_a_id in history_ids
        assert coordinator_b_id in history_ids

# =======================================================================
# Shared reason validation: rejection & cancellation follow the same
# rules as clarification comments (validate_descriptive_text)
# =======================================================================

@pytest.mark.parametrize("invalid_reason", ["!!!", "12345", "@@@###", "-----", "123-456-7890"])
def test_reject_event_rejects_symbols_or_digits_only_reason(app, event, coordinator, invalid_reason):
    with app.app_context():
        with pytest.raises(ValueError, match="must contain descriptive text"):
            reject_event(event, coordinator["id"], invalid_reason)


def test_reject_event_rejects_blank_reason_with_shared_validation_message(app, event, coordinator):
    with app.app_context():
        with pytest.raises(ValueError, match="At least one rejection reason is required"):
            reject_event(event, coordinator["id"], "")


def test_reject_event_accepts_reason_with_real_words(app, event, coordinator):
    with app.app_context():
        updated = reject_event(event, coordinator["id"], "Insufficient lead time for setup.")
        assert updated.status == "rejected"
        assert updated.review_reason == "Insufficient lead time for setup."


@pytest.mark.parametrize("invalid_reason", ["!!!", "12345", "", "   "])
def test_validate_descriptive_text_rejects_invalid_cancellation_reason(invalid_reason):
    # Cancellation reuses this exact shared helper (see cancel_event_route
    # in routes.py) — testing it directly here proves cancellation follows
    # the same rule as clarification comments and rejection reasons.
    with pytest.raises(ValueError):
        validate_descriptive_text(invalid_reason, "cancellation reason")


def test_validate_descriptive_text_accepts_a_real_cancellation_reason():
    validate_descriptive_text("Venue became unavailable due to flooding.", "cancellation reason")


def test_change_status_allows_cancelling_directly_from_under_review(app, event):
    with app.app_context():
        updated = change_status(event, "cancelled", changed_by_id=event.coordinator_id, reason="Testing")
        assert updated.status == "cancelled"


def test_change_status_allows_cancelling_directly_from_submitted(app, event):
    with app.app_context():
        event.status = "submitted"
        updated = change_status(event, "cancelled", changed_by_id=event.coordinator_id, reason="Testing")
        assert updated.status == "cancelled"


# =======================================================================
# Coordinator deletes (withdraws) a clarification request
# =======================================================================

def test_delete_clarification_request_by_assigned_coordinator(app, event, coordinator):
    with app.app_context():
        event.proposed_date = date(2023, 12, 1)
        event.proposed_time = time(10, 0)
        db.session.add(event)
        db.session.commit()

        request_clarification(event, coordinator["id"], "Please confirm the headcount.")
        review_id = event.reviews[-1].id

        updated = delete_clarification_request(event, coordinator["id"], review_id)

        deleted_review = next(r for r in updated.reviews if r.id == review_id)
        assert deleted_review.withdrawn_at is not None
        assert updated.clarification_flag is False  # no other open requests


def test_delete_clarification_request_requires_assigned_coordinator(app, event, coordinator, second_coordinator):
    with app.app_context():
        event.proposed_date = date(2023, 12, 1)
        event.proposed_time = time(10, 0)
        db.session.add(event)
        db.session.commit()

        request_clarification(event, coordinator["id"], "Please confirm the headcount.")
        review_id = event.reviews[-1].id

        with pytest.raises(PermissionError, match="Only the assigned Coordinator can delete a clarification request"):
            delete_clarification_request(event, second_coordinator["id"], review_id)


def test_delete_clarification_request_fails_for_unknown_review_id(app, event, coordinator):
    with app.app_context():
        event.proposed_date = date(2023, 12, 1)
        event.proposed_time = time(10, 0)
        db.session.add(event)
        db.session.commit()

        with pytest.raises(ValueError, match="No such clarification request"):
            delete_clarification_request(event, coordinator["id"], 999999)


def test_cannot_delete_an_already_withdrawn_clarification_request(app, event, coordinator):
    with app.app_context():
        event.proposed_date = date(2023, 12, 1)
        event.proposed_time = time(10, 0)
        db.session.add(event)
        db.session.commit()

        request_clarification(event, coordinator["id"], "Please confirm the headcount.")
        review_id = event.reviews[-1].id
        delete_clarification_request(event, coordinator["id"], review_id)

        with pytest.raises(ValueError, match="already been deleted"):
            delete_clarification_request(event, coordinator["id"], review_id)


def test_cannot_delete_a_clarification_request_that_has_already_been_answered(app, event, coordinator, organiser):
    with app.app_context():
        event.proposed_date = date(2023, 12, 1)
        event.proposed_time = time(10, 0)
        db.session.add(event)
        db.session.commit()

        request_clarification(event, coordinator["id"], "Please confirm the headcount.")
        review_id = event.reviews[-1].id
        respond_to_clarification(event, organiser["id"], review_id, {"comments": "Confirmed at 120."})

        with pytest.raises(ValueError, match="already been responded to"):
            delete_clarification_request(event, coordinator["id"], review_id)


def test_deleting_one_clarification_leaves_another_open_request_intact(app, event, coordinator):
    with app.app_context():
        event.proposed_date = date(2023, 12, 1)
        event.proposed_time = time(10, 0)
        db.session.add(event)
        db.session.commit()

        request_clarification(event, coordinator["id"], "First question.")
        request_clarification(event, coordinator["id"], "Second question.")
        first_id, second_id = [r.id for r in event.reviews if r.action == "clarification_requested"]

        updated = delete_clarification_request(event, coordinator["id"], first_id)

        # the second, still-open request keeps the flag set
        assert updated.clarification_flag is True

        thread = get_clarification_thread(updated)
        first_entry = next(t for t in thread if t["reviewId"] == first_id)
        second_entry = next(t for t in thread if t["reviewId"] == second_id)
        assert first_entry["withdrawn"] is True
        assert second_entry["withdrawn"] is False


def test_get_clarification_thread_marks_withdrawn_requests(app, event, coordinator):
    with app.app_context():
        event.proposed_date = date(2023, 12, 1)
        event.proposed_time = time(10, 0)
        db.session.add(event)
        db.session.commit()

        request_clarification(event, coordinator["id"], "Please confirm the headcount.")
        review_id = event.reviews[-1].id
        delete_clarification_request(event, coordinator["id"], review_id)

        thread = get_clarification_thread(event)
        assert thread[0]["withdrawn"] is True
        assert thread[0]["response"] is None


# =======================================================================
# Organiser cannot respond to a clarification once the event has reached
# a terminal outcome (approved / rejected / cancelled)
# =======================================================================

@pytest.mark.parametrize("terminal_status", ["approved", "rejected", "cancelled"])
def test_cannot_respond_to_clarification_once_event_is_in_a_terminal_status(
    app, event, coordinator, organiser, terminal_status
):
    with app.app_context():
        event.proposed_date = date(2023, 12, 1)
        event.proposed_time = time(10, 0)
        db.session.add(event)
        db.session.commit()

        request_clarification(event, coordinator["id"], "Please confirm the headcount.")
        review_id = event.reviews[-1].id

        event.status = terminal_status  # simulate the event having since been decided
        db.session.commit()

        with pytest.raises(ValueError, match=f"once the request has been {terminal_status}"):
            respond_to_clarification(event, organiser["id"], review_id, {"comments": "Too late now."})


def test_can_still_respond_while_status_is_submitted_or_under_review(app, event, coordinator, organiser):
    with app.app_context():
        event.proposed_date = date(2023, 12, 1)
        event.proposed_time = time(10, 0)
        db.session.add(event)
        db.session.commit()

        request_clarification(event, coordinator["id"], "Please confirm the headcount.")
        review_id = event.reviews[-1].id

        updated = respond_to_clarification(event, organiser["id"], review_id, {"comments": "Confirmed at 120."})
        assert updated.clarification_flag is False


# =======================================================================
# Confirmation gate for approve / reject / cancel
# (app.events.routes._require_confirmation is the actual decision logic
# behind the HTTP 409 "please confirm" response; tested directly since
# it needs no request/JWT context of its own — just an app context for
# jsonify)
# =======================================================================

def test_require_confirmation_prompts_when_not_yet_confirmed(app, event):
    with app.app_context():
        event.clarification_flag = False
        result = _require_confirmation(event, {}, "approve")
        assert result is not None
        response, status_code = result
        assert status_code == 409
        body = response.get_json()
        assert body["requiresConfirmation"] is True
        assert body["hasUnresolvedClarification"] is False
        assert "approve" in body["message"]


@pytest.mark.parametrize("action_label", ["approve", "reject", "cancel"])
def test_require_confirmation_warns_about_unresolved_clarification(app, event, action_label):
    with app.app_context():
        event.clarification_flag = True
        result = _require_confirmation(event, {}, action_label)
        assert result is not None
        response, status_code = result
        body = response.get_json()
        assert status_code == 409
        assert body["hasUnresolvedClarification"] is True
        assert "unresolved clarification" in body["message"].lower()
        assert action_label in body["message"]


def test_require_confirmation_returns_none_once_confirmed(app, event):
    with app.app_context():
        event.clarification_flag = True  # even with an unresolved clarification...
        result = _require_confirmation(event, {"confirmed": True}, "reject")
        assert result is None  # ...explicit confirmation always lets the action through


def test_require_confirmation_is_required_even_without_any_unresolved_clarification(app, event):
    with app.app_context():
        event.clarification_flag = False
        result = _require_confirmation(event, {}, "cancel")
        assert result is not None  # confirmation is unconditional, not just a warning-triggered thing


def test_review_display_helpers_format_optional_and_equipment_values():
    event = Event(
        name="Display helper event",
        proposed_date=date(2030, 6, 1),
        required_facilities=[],
        registration_required=False,
    )

    assert event_routes._nil_if_empty(None) == "NIL"
    assert event_routes._nil_if_empty("  ") == "NIL"
    assert event_routes._nil_if_empty([]) == "NIL"
    assert event_routes._nil_if_empty({}) == "NIL"
    assert event_routes._nil_if_empty(0) == 0
    assert event_routes._nil_if_empty(False) is False

    assert event_routes._format_proposed_date_time(event) == "2030-06-01"
    event.proposed_date = None
    event.proposed_time = time(14, 30)
    assert event_routes._format_proposed_date_time(event) == "14:30:00"
    event.proposed_time = None
    assert event_routes._format_proposed_date_time(event) is None

    assert event_routes._venue_requirements_value(event) == "NIL"
    event.capacity_needed = 0
    assert event_routes._venue_requirements_value(event) == {
        "capacityNeeded": 0,
        "requiredLayout": "NIL",
        "requiredFacilities": "NIL",
    }

    assert event_routes._equipment_requirements_value(event) == "NIL"
    event.equipment_requirements = [
        EventEquipmentRequirement(
            equipment_type="",
            quantity=0,
            technical_notes=None,
        )
    ]
    assert event_routes._equipment_requirements_value(event) == [
        {"type": "NIL", "quantity": 0, "technicalNotes": "NIL"}
    ]


def test_event_route_cancel_uses_confirmation_gate_and_validation_errors(app, client, auth_header):
    with app.app_context():
        coordinator = User(
            name="Coord", email="coord.route@test.com", password_hash=generate_password_hash("password")
        )
        coordinator.roles = [Role.query.filter_by(name="event_coordinator").first()]
        db.session.add(coordinator)
        db.session.commit()

        event = Event(
            organiser_id=100,
            coordinator_id=coordinator.id,
            status="confirmed",
            name="Route cancel event",
            purpose="Testing route",
            description="Event to cancel",
            proposed_date=date(2030, 1, 1),
            proposed_time=time(9, 0),
            expected_attendance=40,
            required_layout="theatre",
            accessibility_needs="Step-free access",
            registration_required=False,
        )
        db.session.add(event)
        db.session.commit()

        headers = auth_header("coord.route@test.com")

        response = client.post(f"/api/events/{event.id}/cancel", headers=headers, json={"reason": "No longer happening"})
        assert response.status_code == 409
        assert response.get_json()["requiresConfirmation"] is True

        response = client.post(f"/api/events/{event.id}/cancel", headers=headers, json={"reason": "!!!"})
        assert response.status_code == 400
        assert "error" in response.get_json()

        response = client.post(f"/api/events/{event.id}/cancel", headers=headers, json={"reason": "No longer happening", "confirmed": True})
        assert response.status_code == 200
        assert response.get_json()["status"] == "cancelled"


def test_event_route_status_and_safety_handlers_cover_error_paths(app, client, auth_header, monkeypatch):
    with app.app_context():
        coordinator = User(
            name="Safety Coord", email="status.route@test.com", password_hash=generate_password_hash("password")
        )
        coordinator.roles = [Role.query.filter_by(name="event_coordinator").first()]
        db.session.add(coordinator)
        db.session.commit()

        event = Event(
            organiser_id=100,
            coordinator_id=coordinator.id,
            status="confirmed",
            name="Status route event",
            purpose="Testing status",
            description="Event for status route",
            proposed_date=date(2030, 2, 1),
            proposed_time=time(10, 0),
            expected_attendance=50,
            required_layout="theatre",
            accessibility_needs="Wheelchair access",
            registration_required=False,
        )
        db.session.add(event)
        db.session.commit()

        headers = auth_header("status.route@test.com")

        response = client.post(f"/api/events/{event.id}/status", headers=headers, json={"status": "safety_approved"})
        assert response.status_code == 403

        response = client.post(f"/api/events/{event.id}/status", headers=headers, json={"status": "nonsense"})
        assert response.status_code == 400

        monkeypatch.setattr(event_routes.status_service, "revert_to_planning", lambda event_obj, uid, reason: event_obj)
        response = client.post(f"/api/events/{event.id}/status", headers=headers, json={"status": "planning", "reason": "Change"})
        assert response.status_code == 200

        safety_officer = User(
            name="Safety Officer", email="safety.route@test.com", password_hash=generate_password_hash("password")
        )
        safety_officer.roles = [Role.query.filter_by(name="safety_officer").first()]
        db.session.add(safety_officer)
        db.session.commit()

        safety_headers = auth_header("safety.route@test.com")
        safety_event = Event(
            organiser_id=100,
            coordinator_id=coordinator.id,
            status="planning",
            name="Safety event",
            purpose="Safety test",
            description="Safety route",
            proposed_date=date(2030, 3, 1),
            proposed_time=time(11, 0),
            expected_attendance=60,
            required_layout="theatre",
            accessibility_needs="Step-free access",
            registration_required=False,
        )
        db.session.add(safety_event)
        db.session.commit()

        response = client.get(f"/api/events/{safety_event.id}/safety-assessment", headers=safety_headers)
        assert response.status_code == 200

        monkeypatch.setattr(event_routes.safety, "save_assessment", lambda event_obj, user_obj, values: None)
        response = client.put(f"/api/events/{safety_event.id}/safety-assessment", headers=safety_headers, json={"factorAssessments": []})
        assert response.status_code == 200

        monkeypatch.setattr(event_routes.safety, "save_assessment", lambda *args, **kwargs: (_ for _ in ()).throw(ValueError("bad")))
        response = client.put(f"/api/events/{safety_event.id}/safety-assessment", headers=safety_headers, json={"factorAssessments": []})
        assert response.status_code == 400

        monkeypatch.setattr(event_routes.safety, "review_safety_check", lambda event_obj, user_obj, *args, **kwargs: event_obj)
        response = client.post(f"/api/events/{safety_event.id}/safety-review", headers=safety_headers, json={"decision": "approved"})
        assert response.status_code == 200

        monkeypatch.setattr(event_routes.safety, "review_safety_check", lambda *args, **kwargs: (_ for _ in ()).throw(event_routes.safety.SafetyReviewConflictError("conflict")))
        response = client.post(f"/api/events/{safety_event.id}/safety-review", headers=safety_headers, json={"decision": "approved"})
        assert response.status_code == 409

        monkeypatch.setattr(
            event_routes.safety,
            "review_safety_check",
            lambda *args, **kwargs: (_ for _ in ()).throw(event_routes.safety.SafetyReviewValidationError(["field: bad"])),
        )
        response = client.post(f"/api/events/{safety_event.id}/safety-review", headers=safety_headers, json={"decision": "approved"})
        assert response.status_code == 400

        response = client.get(f"/api/events/{999999}/safety-assessment", headers=safety_headers)
        assert response.status_code == 404


def test_review_decision_is_empty_before_any_decision(app):
    with app.app_context():
        pending = _persist_event()
        decision = pending.to_dict()["reviewDecision"]
        assert decision["outcome"] is None
        assert decision["reason"] is None
        assert decision["timestamp"] is None
        assert decision["coordinatorId"] is None
        assert decision["coordinatorName"] is None


def test_rejection_decision_records_outcome_reason_coordinator_and_time(app, two_real_coordinators):
    with app.app_context():
        coordinator_a_id, _ = two_real_coordinators
        rejected = _persist_rejected_event(coordinator_a_id, reason="Insufficient lead time.")

        decision = rejected.to_dict()["reviewDecision"]
        assert decision["outcome"] == "rejected"
        assert decision["reason"] == "Insufficient lead time."
        assert decision["coordinatorId"] == coordinator_a_id
        assert decision["coordinatorName"] == "Real Coordinator A"
        datetime.fromisoformat(decision["timestamp"])  # valid ISO timestamp, raises if not


def test_approval_decision_records_outcome_comments_coordinator_and_time(app, two_real_coordinators):
    with app.app_context():
        coordinator_a_id, _ = two_real_coordinators
        event = _persist_event(coordinator_id=coordinator_a_id)
        approve_event(event, coordinator_a_id, "Looks good.")

        decision = event.to_dict()["reviewDecision"]
        assert decision["outcome"] == "approved"
        assert decision["reason"] == "Looks good."
        assert decision["coordinatorId"] == coordinator_a_id
        assert decision["coordinatorName"] == "Real Coordinator A"
        datetime.fromisoformat(decision["timestamp"])


def test_approval_without_comments_has_no_reason(app, two_real_coordinators):
    with app.app_context():
        coordinator_a_id, _ = two_real_coordinators
        event = _persist_event(coordinator_id=coordinator_a_id)
        approve_event(event, coordinator_a_id)

        decision = event.to_dict()["reviewDecision"]
        assert decision["outcome"] == "approved"
        assert decision["reason"] is None
        assert decision["coordinatorName"] == "Real Coordinator A"


def test_decision_is_attributed_to_the_coordinator_who_actually_decided(app, two_real_coordinators):
    with app.app_context():
        coordinator_a_id, coordinator_b_id = two_real_coordinators
        event = _persist_event(coordinator_id=coordinator_a_id)
        reassign_coordinator(event, User.query.get(coordinator_b_id))
        approve_event(event, coordinator_b_id, "Approved after handover.")

        decision = event.to_dict()["reviewDecision"]
        assert decision["coordinatorId"] == coordinator_b_id
        assert decision["coordinatorName"] == "Real Coordinator B"

@pytest.mark.parametrize(
    "status",
    ["draft", "submitted", "under_review", "approved", "planning", "confirmed", "completed", "cancelled"],
)
def test_only_rejected_requests_can_be_resubmitted(app, status):
    with app.app_context():
        event = _persist_event(status=status)
        assert can_be_resubmitted(event) is False


def test_rejected_request_that_was_never_resubmitted_can_be_resubmitted(app, two_real_coordinators):
    with app.app_context():
        coordinator_a_id, _ = two_real_coordinators
        rejected = _persist_rejected_event(coordinator_a_id)
        assert can_be_resubmitted(rejected) is True


def test_rejected_request_cannot_be_resubmitted_twice(app, two_real_coordinators):
    with app.app_context():
        coordinator_a_id, _ = two_real_coordinators
        original = _persist_rejected_event(coordinator_a_id)
        resubmission = resubmit_rejected_event(original, original.organiser_id, {})

        assert can_be_resubmitted(original) is False     # its one resubmission is used
        assert can_be_resubmitted(resubmission) is False  # under review, not rejected


def test_each_generation_in_a_resubmission_chain_gets_exactly_one_resubmission(app, two_real_coordinators):
    with app.app_context():
        coordinator_a_id, _ = two_real_coordinators
        first = _persist_rejected_event(coordinator_a_id, reason="First rejection reason.")
        assert can_be_resubmitted(first) is True

        second = _resubmit_and_assign(first)
        reject_event(second, second.coordinator_id, "Second rejection reason.")
        # the rejected resubmission is a new rejected request with its own single resubmission
        assert can_be_resubmitted(second) is True
        assert can_be_resubmitted(first) is False

        third = _resubmit_and_assign(second)
        assert can_be_resubmitted(second) is False
        assert can_be_resubmitted(first) is False
        assert third.resubmitted_from_event_id == second.id
        assert third.status == "under_review"

def test_resubmission_creates_a_new_linked_event_under_review(app, two_real_coordinators):
    with app.app_context():
        coordinator_a_id, coordinator_b_id = two_real_coordinators
        original = _persist_rejected_event(coordinator_a_id, reason="Date clashes with another event.")

        new_event = resubmit_rejected_event(original, original.organiser_id, {})

        assert new_event.id != original.id
        assert new_event.resubmitted_from_event_id == original.id
        # Waits in the Unassigned queue until a Coordinator Lead assigns it.
        assert new_event.status == "submitted"
        assert new_event.submitted_at is not None
        assert new_event.coordinator_id is None

        lead_assign(new_event, get_next_coordinator())
        assert new_event.status == "under_review"
        assert new_event.coordinator_id in (coordinator_a_id, coordinator_b_id)

        # the original stays as the permanent rejected record
        assert original.status == "rejected"
        assert original.review_outcome == "rejected"
        assert original.review_reason == "Date clashes with another event."


def test_resubmission_carries_over_original_details_when_nothing_is_edited(app, two_real_coordinators):
    with app.app_context():
        coordinator_a_id, _ = two_real_coordinators
        original = _persist_rejected_event(coordinator_a_id)

        new_event = resubmit_rejected_event(original, original.organiser_id, {})

        for attr in (
            "name",
            "purpose",
            "description",
            "proposed_date",
            "proposed_time",
            "expected_attendance",
            "capacity_needed",
            "required_layout",
            "accessibility_needs",
            "registration_required",
            "intended_capacity",
        ):
            assert getattr(new_event, attr) == getattr(original, attr), attr


def test_resubmission_edits_apply_to_the_new_event_only(app, two_real_coordinators):
    with app.app_context():
        coordinator_a_id, _ = two_real_coordinators
        original = _persist_rejected_event(coordinator_a_id)

        new_event = resubmit_rejected_event(
            original,
            original.organiser_id,
            {"description": "Revised description addressing the rejection.", "proposed_date": date(2030, 7, 15)},
        )

        assert new_event.description == "Revised description addressing the rejection."
        assert new_event.proposed_date == date(2030, 7, 15)
        assert original.description == "Original description."
        assert original.proposed_date == date(2030, 6, 1)


def test_resubmission_does_not_inherit_the_previous_decision(app, two_real_coordinators):
    with app.app_context():
        coordinator_a_id, _ = two_real_coordinators
        original = _persist_rejected_event(coordinator_a_id)

        new_event = resubmit_rejected_event(original, original.organiser_id, {})

        assert new_event.review_outcome is None
        assert new_event.review_reason is None
        assert new_event.review_timestamp is None
        assert new_event.review_coordinator_id is None


def test_each_resubmission_shows_its_own_latest_decision(app, two_real_coordinators):
    with app.app_context():
        coordinator_a_id, _ = two_real_coordinators
        first = _persist_rejected_event(coordinator_a_id, reason="First rejection reason.")
        second = _resubmit_and_assign(first)
        reject_event(second, second.coordinator_id, "Still missing the catering plan.")

        assert second.status == "rejected"
        assert second.to_dict()["reviewDecision"]["reason"] == "Still missing the catering plan."
        assert first.to_dict()["reviewDecision"]["reason"] == "First rejection reason."


def test_same_rejected_request_cannot_be_resubmitted_twice(app, two_real_coordinators):
    with app.app_context():
        coordinator_a_id, _ = two_real_coordinators
        original = _persist_rejected_event(coordinator_a_id)
        resubmit_rejected_event(original, original.organiser_id, {})

        with pytest.raises(ValueError, match="already been resubmitted"):
            resubmit_rejected_event(original, original.organiser_id, {})

        # the blocked attempt must not leave a second linked record behind
        assert Event.query.filter_by(resubmitted_from_event_id=original.id).count() == 1


def test_resubmission_requires_the_owning_organiser(app, two_real_coordinators):
    with app.app_context():
        coordinator_a_id, _ = two_real_coordinators
        original = _persist_rejected_event(coordinator_a_id)

        with pytest.raises(PermissionError, match="Only the requesting Organiser can resubmit this request"):
            resubmit_rejected_event(original, 999, {})

        assert Event.query.filter_by(resubmitted_from_event_id=original.id).count() == 0


@pytest.mark.parametrize("status", ["draft", "under_review", "approved", "cancelled"])
def test_only_a_rejected_request_can_be_resubmitted(app, two_real_coordinators, status):
    with app.app_context():
        coordinator_a_id, _ = two_real_coordinators
        event = _persist_event(coordinator_id=coordinator_a_id, status=status)

        with pytest.raises(ValueError, match="Only a rejected request can be resubmitted"):
            resubmit_rejected_event(event, event.organiser_id, {})

def test_first_submission_has_no_prior_decisions(app, two_real_coordinators):
    with app.app_context():
        coordinator_a_id, _ = two_real_coordinators
        event = _persist_event(coordinator_id=coordinator_a_id)
        assert get_prior_rejection_decisions(event) == []


def test_prior_decisions_list_earlier_rejections_oldest_first(app, two_real_coordinators):
    with app.app_context():
        coordinator_a_id, _ = two_real_coordinators
        first, second, third = _build_three_generation_chain(coordinator_a_id)

        prior = get_prior_rejection_decisions(third)

        assert [d["eventId"] for d in prior] == [first.id, second.id]
        assert [d["outcome"] for d in prior] == ["rejected", "rejected"]
        assert [d["reason"] for d in prior] == ["First rejection reason.", "Second rejection reason."]
        assert all(d["coordinatorName"] in ("Real Coordinator A", "Real Coordinator B") for d in prior)


def test_prior_decisions_exclude_the_events_own_decision(app, two_real_coordinators):
    with app.app_context():
        coordinator_a_id, _ = two_real_coordinators
        first, second, _third = _build_three_generation_chain(coordinator_a_id)

        # second was itself rejected, but its own decision is shown separately
        prior = get_prior_rejection_decisions(second)
        assert [d["eventId"] for d in prior] == [first.id]


def test_prior_decisions_ignore_unrelated_events(app, two_real_coordinators):
    with app.app_context():
        coordinator_a_id, _ = two_real_coordinators
        first, second, third = _build_three_generation_chain(coordinator_a_id)
        unrelated = _persist_rejected_event(coordinator_a_id, reason="Unrelated rejection.")

        prior = get_prior_rejection_decisions(third)
        assert unrelated.id not in [d["eventId"] for d in prior]


def test_full_review_history_spans_every_generation_oldest_first(app, two_real_coordinators):
    with app.app_context():
        coordinator_a_id, _ = two_real_coordinators
        first, second, third = _build_three_generation_chain(coordinator_a_id)

        history = get_full_review_history(third)

        assert [(h["eventId"], h["action"]) for h in history] == [
            (first.id, "rejected"),
            (second.id, "clarification_requested"),
            (second.id, "rejected"),
        ]
        assert [h["comments"] for h in history] == [
            "First rejection reason.",
            "Please clarify the catering plan.",
            "Second rejection reason.",
        ]


def test_full_review_history_flags_which_entries_belong_to_the_current_submission(app, two_real_coordinators):
    with app.app_context():
        coordinator_a_id, _ = two_real_coordinators
        _first, second, _third = _build_three_generation_chain(coordinator_a_id)

        history = get_full_review_history(second)

        # first's rejection is an earlier submission; second's two entries are current
        assert [h["isCurrentSubmission"] for h in history] == [False, True, True]


def test_full_review_history_for_an_unresubmitted_event_contains_only_its_own_entries(app, two_real_coordinators):
    with app.app_context():
        coordinator_a_id, _ = two_real_coordinators
        event = _persist_event(coordinator_id=coordinator_a_id)
        request_clarification(event, coordinator_a_id, "Please confirm the headcount.")

        history = get_full_review_history(event)

        assert len(history) == 1
        assert history[0]["action"] == "clarification_requested"
        assert history[0]["comments"] == "Please confirm the headcount."
        assert history[0]["isCurrentSubmission"] is True


def test_cannot_respond_to_withdrawn_clarification(app):
    with app.app_context():
        event = _persist_event(coordinator_id=200)
        request_clarification(event, 200, "Please confirm the headcount.")
        review_id = event.reviews[-1].id
        delete_clarification_request(event, 200, review_id)

        with pytest.raises(ValueError, match="withdrawn"):
            respond_to_clarification(event, 100, review_id, {"comments": "Confirmed at 80."})

        assert EventClarificationResponse.query.filter_by(review_id=review_id).count() == 0


def test_response_integrity_error_rolls_back_and_reports_duplicate(app):
    with app.app_context():
        event = _persist_event(coordinator_id=200)
        request_clarification(event, 200, "Please confirm the headcount.")
        review_id = event.reviews[-1].id
        event_id = event.id
        error = IntegrityError("INSERT", {}, Exception("duplicate response"))
        with patch.object(db.session, "commit", side_effect=error), patch.object(
            db.session, "rollback", wraps=db.session.rollback
        ) as rollback:
            with pytest.raises(ValueError, match="already been responded to"):
                respond_to_clarification(event, 100, review_id, {"comments": "Confirmed at 80."})
            rollback.assert_called_once()

        assert EventClarificationResponse.query.filter_by(review_id=review_id).count() == 0
        assert db.session.get(Event, event_id).clarification_flag is True


def test_clarification_thread_ignores_other_review_actions(app):
    with app.app_context():
        event = _persist_event(coordinator_id=200)
        request_clarification(event, 200, "Please confirm the headcount.")
        review_id = event.reviews[-1].id
        db.session.add(EventReview(event_id=event.id, coordinator_id=200, action="approved"))
        db.session.commit()
        db.session.expire(event, ["reviews"])

        thread = get_clarification_thread(event)

        assert len(thread) == 1
        assert thread[0]["reviewId"] == review_id
        assert thread[0]["request"]["comments"] == "Please confirm the headcount."


@pytest.mark.parametrize("broken_chain", ["missing_parent", "cycle"])
def test_review_history_stops_at_missing_or_repeated_parent(app, broken_chain):
    with app.app_context():
        event = _persist_event(coordinator_id=200)
        db.session.add(EventReview(
            event_id=event.id, coordinator_id=200, action="rejected", comments="Revise the plan."
        ))
        db.session.commit()
        # Simulate legacy/corrupt links in memory without persisting invalid foreign keys.
        with db.session.no_autoflush:
            event.resubmitted_from_event_id = 999999 if broken_chain == "missing_parent" else event.id
            history = get_full_review_history(event)
            prior = get_prior_rejection_decisions(event)

        assert len(history) == 1
        assert history[0]["eventId"] == event.id
        assert history[0]["comments"] == "Revise the plan."
        assert history[0]["isCurrentSubmission"] is True
        assert prior == []


@pytest.mark.parametrize("timestamp", [None, datetime(2026, 11, 4, 9, 30)])
def test_event_review_to_dict(timestamp):
    review = EventReview(
        id=7, event_id=42, coordinator_id=200, action="clarification_requested",
        comments="Please confirm the headcount.", withdrawn_at=timestamp, created_at=timestamp,
    )

    assert review.to_dict() == {
        "id": 7,
        "coordinatorId": 200,
        "action": "clarification_requested",
        "comments": "Please confirm the headcount.",
        "withdrawnAt": "2026-11-04T09:30:00" if timestamp else None,
        "createdAt": "2026-11-04T09:30:00" if timestamp else None,
    }
