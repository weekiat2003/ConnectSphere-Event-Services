"""Integration tests for Event Status Management: Stories 1-4.

Every test here goes through a real HTTP request with a real JWT via the Flask test client.
"""
from datetime import date, time, timedelta

import pytest

from app.extensions import db
from app.models.event import Event, EventStatusHistory

ORG = "organiser@test.com"
COORD = "coordinator@test.com"


def _get(client, headers, event_id):
    return client.get(f"/api/events/{event_id}", headers=headers)


def _status(client, headers, event_id):
    res = _get(client, headers, event_id)
    assert res.status_code == 200, res.get_json()
    return res.get_json()["status"]


# =====================================================================
# Story 1: Consistent status display
# =====================================================================

class TestAC1StatusShownOverHTTP:
    """AC1: status is clearly shown on detail and list views, and stays
    consistent with the actions actually performed on the event."""

    def test_detail_endpoint_shows_status(self, client, auth_header, organiser, make_event):
        # The detail endpoint returns the real status + its display label.
        event_id = make_event(organiser, status="planning")
        body = _get(client, auth_header(ORG), event_id).get_json()
        assert body["status"] == "planning"
        assert body["statusLabel"] == "Planning"
        assert body["statusValid"] is True

    def test_list_endpoint_shows_status(self, client, auth_header, organiser, make_event):
        # The organiser's own list also carries status + label per row.
        make_event(organiser, status="confirmed")
        rows = client.get("/api/events/mine", headers=auth_header(ORG)).get_json()
        assert rows[0]["status"] == "confirmed"
        assert rows[0]["statusLabel"] == "Confirmed"

    def test_status_reflects_real_submit_and_approve_actions(
        self, client, auth_header, organiser, coordinator, make_event
    ):
        # Full lifecycle through the real endpoints: draft -> under_review
        # -> planning (approval now chains straight to planning, per
        # Story 3 AC1, not "approved").
        org, coord = auth_header(ORG), auth_header(COORD)
        event_id = make_event(
            organiser,
            proposed_time=time(9, 0),
            capacity_needed=100,
            required_layout="theatre",
            accessibility_needs="None",
        )
        assert _status(client, org, event_id) == "draft"

        res = client.post(f"/api/events/{event_id}/submit", headers=org)
        assert res.status_code == 200, res.get_json()
        assert _status(client, org, event_id) == "under_review"
        assert _status(client, coord, event_id) == "under_review"

        res = client.post(
            f"/api/events/{event_id}/approve",
            headers=coord,
            json={"comments": "ok", "confirmed": True},
        )
        assert res.status_code == 200, res.get_json()
        assert _status(client, org, event_id) == "planning"

    def test_status_reflects_real_rejection(
        self, client, auth_header, organiser, coordinator, make_event
    ):
        # Rejection requires explicit confirmation too.
        event_id = make_event(organiser, status="under_review", coordinator_id=coordinator)
        res = client.post(
            f"/api/events/{event_id}/reject",
            headers=auth_header(COORD),
            json={"reason": "No venue", "confirmed": True},
        )
        assert res.status_code == 200, res.get_json()
        assert _status(client, auth_header(ORG), event_id) == "rejected"


class TestAC2ListIntegrityOverHTTP:
    """AC2: a list of multiple events shows each event's own status, with
    no stale or cross-contaminated values."""

    def test_each_row_reflects_its_own_status(self, client, auth_header, organiser, make_event):
        ids = {
            s: make_event(organiser, status=s, name=f"Event {s}")
            for s in ("draft", "under_review", "confirmed", "rejected")
        }
        rows = {r["id"]: r for r in client.get("/api/events/mine", headers=auth_header(ORG)).get_json()}
        assert len(rows) == 4
        for status, event_id in ids.items():
            assert rows[event_id]["status"] == status
            assert rows[event_id]["name"] == f"Event {status}"

    def test_changing_one_event_does_not_affect_others_in_the_list(
        self, client, auth_header, organiser, coordinator, make_event
    ):
        a = make_event(organiser, "under_review", coordinator_id=coordinator, name="A")
        b = make_event(organiser, "under_review", coordinator_id=coordinator, name="B")
        client.post(
            f"/api/events/{a}/approve", headers=auth_header(COORD), json={"confirmed": True}
        )
        rows = {
            r["id"]: r["status"]
            for r in client.get("/api/events/mine", headers=auth_header(ORG)).get_json()
        }
        assert rows[a] == "planning"
        assert rows[b] == "under_review"


class TestAC3PermissionsOverHTTP:
    """AC3: without permission to view an event, its status is not shown.
    Uses real login + JWT, not a hand-built SimpleNamespace."""

    def test_other_organiser_cannot_see_event_detail(
        self, client, auth_header, organiser, make_user, make_event
    ):
        make_user("other@test.com", ["event_organiser"])
        event_id = make_event(organiser, status="confirmed")
        res = _get(client, auth_header("other@test.com"), event_id)
        assert res.status_code == 404
        assert "status" not in res.get_json()

    def test_other_organiser_list_is_empty(
        self, client, auth_header, organiser, make_user, make_event
    ):
        make_user("other@test.com", ["event_organiser"])
        make_event(organiser, status="confirmed")
        rows = client.get("/api/events/mine", headers=auth_header("other@test.com")).get_json()
        assert rows == []

    def test_attendee_cannot_see_event(self, client, auth_header, organiser, make_user, make_event):
        make_user("att@test.com", ["attendee"])
        event_id = make_event(organiser, status="confirmed")
        res = _get(client, auth_header("att@test.com"), event_id)
        assert res.status_code == 404
        assert "status" not in res.get_json()

    def test_unauthenticated_request_cannot_see_event(self, client, organiser, make_event):
        event_id = make_event(organiser, status="confirmed")
        res = client.get(f"/api/events/{event_id}")
        assert res.status_code == 401
        assert "status" not in res.get_json()

    @pytest.mark.parametrize("role", ["event_coordinator", "venue_staff", "technical_support_staff"])
    def test_internal_staff_cannot_see_someone_elses_draft(
        self, client, auth_header, organiser, make_user, make_event, role
    ):
        make_user(f"{role}@x.com", [role])
        draft_id = make_event(organiser, status="draft")
        headers = auth_header(f"{role}@x.com")

        assert _get(client, headers, draft_id).status_code == 404

        res = client.get("/api/events", headers=headers)
        assert res.status_code == 200
        listed_ids = [e["id"] for e in res.get_json()]
        assert draft_id not in listed_ids

    @pytest.mark.parametrize("role", ["event_coordinator", "venue_staff", "technical_support_staff"])
    def test_internal_staff_can_see_submitted_events(
        self, client, auth_header, organiser, make_user, make_event, role
    ):
        make_user(f"{role}@x.com", [role])
        event_id = make_event(organiser, status="planning")
        assert _status(client, auth_header(f"{role}@x.com"), event_id) == "planning"


class TestAC4RefreshOverHTTP:
    """AC4: if status changes while a detail page is open, refreshing
    (i.e. re-fetching) shows the updated status."""

    def test_second_fetch_returns_the_new_status(
        self, client, auth_header, organiser, coordinator, make_event
    ):
        org, coord = auth_header(ORG), auth_header(COORD)
        event_id = make_event(organiser, "under_review", coordinator_id=coordinator)
        assert _status(client, org, event_id) == "under_review"  # page loaded here

        client.post(f"/api/events/{event_id}/approve", headers=coord, json={"confirmed": True})
        assert _status(client, org, event_id) == "planning"  # refresh #1

        client.post(
            f"/api/events/{event_id}/status",
            headers=coord,
            json={"status": "cancelled", "reason": "Client withdrew"},
        )
        assert _status(client, org, event_id) == "cancelled"  # refresh #2


class TestAC5DraftDefaultOverHTTP:
    """AC5: a newly created draft event shows status 'draft' by default,
    through the real draft-creation endpoints."""

    def test_draft_creation_endpoint_defaults_to_draft(self, client, auth_header, organiser):
        org = auth_header(ORG)
        res = client.post("/api/events/drafts", headers=org, json={"name": "Partial"})
        assert res.status_code == 201
        body = res.get_json()
        assert body["status"] == "draft"
        assert body["statusLabel"] == "Draft"
        assert _status(client, org, body["id"]) == "draft"

    def test_empty_draft_still_defaults_to_draft(self, client, auth_header, organiser):
        res = client.post("/api/events/drafts", headers=auth_header(ORG), json={})
        assert res.get_json()["status"] == "draft"

    def test_create_event_without_submit_flag_stays_draft(self, client, auth_header, organiser):
        res = client.post("/api/events", headers=auth_header(ORG), json={"name": "x"})
        assert res.get_json()["status"] == "draft"

    def test_new_draft_is_listed_with_draft_status(self, client, auth_header, organiser):
        org = auth_header(ORG)
        client.post("/api/events/drafts", headers=org, json={"name": "D"})
        rows = client.get("/api/events/mine", headers=org).get_json()
        assert [r["status"] for r in rows] == ["draft"]


class TestAC6FallbackOverHTTP:
    """AC6: an unrecognised status reaches the real API response with the
    fallback label, and a bad row doesn't break the rest of a list."""

    def test_detail_endpoint_falls_back_for_bad_status(
        self, client, auth_header, organiser, make_event
    ):
        event_id = make_event(organiser, status="banana")
        body = _get(client, auth_header(ORG), event_id).get_json()
        assert body["statusValid"] is False
        assert body["statusLabel"] == "Unknown status"

    def test_bad_row_does_not_break_the_rest_of_the_list(
        self, client, auth_header, organiser, make_event
    ):
        good = make_event(organiser, status="confirmed")
        bad = make_event(organiser, status="banana")
        rows = {
            r["id"]: r for r in client.get("/api/events/mine", headers=auth_header(ORG)).get_json()
        }
        assert rows[good]["statusValid"] is True
        assert rows[bad]["statusValid"] is False


# =====================================================================
# Story 2: Organiser views status of all their requests
#
# /api/events/mine returns a plain JSON array (same shape whether or not
# pagination params are used); pagination metadata rides in response
# headers: X-Total-Count, X-Page, X-Per-Page, X-Total-Pages.
# =====================================================================

def _mine(client, headers, **params):
    return client.get("/api/events/mine", headers=headers, query_string=params)


class TestAC1StatusShownForEachRequest:
    def test_each_request_shows_its_current_status(self, client, auth_header, organiser, make_event):
        # Each row in the organiser's list carries its own live status.
        make_event(organiser, status="draft", name="A")
        make_event(organiser, status="under_review", name="B")
        make_event(organiser, status="confirmed", name="C")

        res = _mine(client, auth_header(ORG))
        assert res.status_code == 200
        rows = {r["name"]: r["status"] for r in res.get_json()}
        assert rows == {"A": "draft", "B": "under_review", "C": "confirmed"}

    def test_status_label_is_present_on_each_row(self, client, auth_header, organiser, make_event):
        # The human-readable label rides alongside the raw status.
        make_event(organiser, status="under_review")
        row = _mine(client, auth_header(ORG)).get_json()[0]
        assert row["statusLabel"] == "Under review"


class TestAC2EmptyStateNotError:
    def test_zero_requests_returns_empty_list_not_error(self, client, auth_header, organiser):
        # An organiser with no requests gets an empty array, not a 4xx/5xx.
        res = _mine(client, auth_header(ORG))
        assert res.status_code == 200
        assert res.get_json() == []
        assert res.headers["X-Total-Count"] == "0"


class TestAC3OnlyOwnRequestsVisible:
    def test_sees_only_own_requests(self, client, auth_header, organiser, make_user, make_event):
        # Another organiser's events never appear in my list.
        other_id = make_user("other@test.com", ["event_organiser"])
        make_event(organiser, status="confirmed", name="Mine")
        make_event(other_id, status="confirmed", name="Not mine")

        names = [r["name"] for r in _mine(client, auth_header(ORG)).get_json()]
        assert names == ["Mine"]

    def test_other_organisers_requests_never_leak_across_pages(
        self, client, auth_header, organiser, make_user, make_event
    ):
        # Same guarantee holds even with pagination in play.
        other_id = make_user("other@test.com", ["event_organiser"])
        for i in range(5):
            make_event(organiser, name=f"Mine {i}")
        for i in range(5):
            make_event(other_id, name=f"Theirs {i}")

        res = _mine(client, auth_header(ORG), page=1, per_page=100)
        body = res.get_json()
        assert res.headers["X-Total-Count"] == "5"
        assert all(r["name"].startswith("Mine") for r in body)


class TestAC4RemainsUsableWithManyRequests:
    @staticmethod
    def _seed_many(make_event, organiser, count):
        base = date(2026, 1, 1)
        for i in range(count):
            make_event(
                organiser,
                name=f"Event {i}",
                proposed_date=base + timedelta(days=i),
                updated_at=base + timedelta(days=i),  # distinct, increasing recency
            )

    def test_large_number_of_requests_is_paginated(self, client, auth_header, organiser, make_event):
        # A large result set is paginated, with correct metadata headers.
        self._seed_many(make_event, organiser, 55)

        res = _mine(client, auth_header(ORG), page=1, per_page=20)
        body = res.get_json()

        assert res.headers["X-Total-Count"] == "55"
        assert len(body) == 20
        assert res.headers["X-Page"] == "1"
        assert res.headers["X-Per-Page"] == "20"
        assert res.headers["X-Total-Pages"] == "3"  # ceil(55 / 20)

    def test_second_page_returns_the_next_slice(self, client, auth_header, organiser, make_event):
        # Pages don't overlap and together cover every row exactly once.
        self._seed_many(make_event, organiser, 55)

        page1 = _mine(client, auth_header(ORG), page=1, per_page=20).get_json()
        page2 = _mine(client, auth_header(ORG), page=2, per_page=20).get_json()
        page3 = _mine(client, auth_header(ORG), page=3, per_page=20).get_json()

        assert len(page1) == 20
        assert len(page2) == 20
        assert len(page3) == 15  # remainder

        ids_seen = set()
        for page in (page1, page2, page3):
            page_ids = {row["id"] for row in page}
            assert not (ids_seen & page_ids), "pages overlapped"
            ids_seen |= page_ids
        assert len(ids_seen) == 55

    def test_results_are_sorted_most_recent_first(self, client, auth_header, organiser, make_event):
        # Most recently updated requests appear first.
        older = make_event(organiser, name="Older", updated_at=date(2026, 1, 1))
        newer = make_event(organiser, name="Newer", updated_at=date(2026, 1, 2))

        ids_in_order = [row["id"] for row in _mine(client, auth_header(ORG)).get_json()]
        assert ids_in_order.index(newer) < ids_in_order.index(older)

    def test_out_of_range_page_returns_empty_not_an_error(
        self, client, auth_header, organiser, make_event
    ):
        # A page number past the end returns an empty list, not an error.
        self._seed_many(make_event, organiser, 5)

        res = _mine(client, auth_header(ORG), page=99, per_page=20)
        assert res.status_code == 200
        assert res.get_json() == []

    def test_per_page_is_capped_to_a_sane_maximum(self, client, auth_header, organiser, make_event):
        # A huge per_page value is clamped rather than honoured literally.
        self._seed_many(make_event, organiser, 10)

        res = _mine(client, auth_header(ORG), page=1, per_page=100000)
        assert int(res.headers["X-Per-Page"]) <= 100

    @pytest.mark.parametrize("bad_page", [0, -1])
    def test_non_positive_page_falls_back_to_page_one(
        self, client, auth_header, organiser, make_event, bad_page
    ):
        # Page 0 or negative falls back to page 1 instead of erroring.
        self._seed_many(make_event, organiser, 5)
        res = _mine(client, auth_header(ORG), page=bad_page, per_page=20)
        assert res.status_code == 200
        assert len(res.get_json()) == 5
        assert res.headers["X-Page"] == "1"

    def test_missing_page_and_per_page_returns_full_unpaginated_list(
        self, client, auth_header, organiser, make_event
    ):
        # No query params at all -> default behaviour, unchanged response
        # shape, same as before pagination existed.
        make_event(organiser)
        res = _mine(client, auth_header(ORG))
        assert res.status_code == 200
        assert isinstance(res.get_json(), list)


# =====================================================================
# Story 3: Arrangements complete -> safety_check -> confirmed
# (HTTP-level ACs only; service-level ACs are in the unit test file)
# =====================================================================

class TestStory3SafetyReviewOverHTTP:
    def test_safety_review_api_confirms_only_after_safety_officer_approval(
        self, client, auth_header, organiser, make_user, make_event
    ):
        # AC3: a Safety Officer hitting the real endpoint with "approved"
        # moves the event all the way to "confirmed".
        from app.events.services import safety

        make_user("safety-api@test.com", ["safety_officer"])
        event_id = make_event(organiser, status="safety_check")

        response = client.post(
            f"/api/events/{event_id}/safety-review",
            headers=auth_header("safety-api@test.com"),
            json={
                "decision": "approved",
                "comments": "Emergency access checked",
                "assessedFactors": sorted(safety.SAFETY_FACTORS),
            },
        )

        assert response.status_code == 200
        assert response.get_json()["status"] == "confirmed"

    def test_coordinator_cannot_bypass_safety_review_with_generic_status_endpoint(
        self, client, auth_header, organiser, coordinator, make_event
    ):
        # AC3: the generic /status endpoint must not let a Coordinator
        # jump straight from safety_check to confirmed.
        event_id = make_event(organiser, status="safety_check", coordinator_id=coordinator)

        response = client.post(
            f"/api/events/{event_id}/status",
            headers=auth_header(COORD),
            json={"status": "confirmed", "reason": "Trying to bypass safety review"},
        )

        assert response.status_code == 400
        with client.application.app_context():
            event = db.session.get(Event, event_id)
            assert event.status == "safety_check"
            assert EventStatusHistory.query.filter_by(
                event_id=event_id, new_status="confirmed"
            ).count() == 0

    def test_venue_staff_can_cancel_booking_through_api(
        self, client, auth_header, organiser, make_user, make_event
    ):
        # AC4: cancelling an approved booking through the real API reverts
        # a confirmed event to planning.
        from app.common.time import utcnow
        from app.models.venue import Venue, VenueBooking

        venue_staff_id = make_user("venue-staff@test.com", ["venue_staff"])
        event_id = make_event(organiser, status="confirmed", capacity_needed=100)

        with client.application.app_context():
            venue = Venue(name="Test Hall", location="Campus", capacity=200, created_by=venue_staff_id)
            db.session.add(venue)
            db.session.flush()
            booking = VenueBooking(
                event_id=event_id,
                venue_id=venue.id,
                requested_by=organiser,
                status="approved",
                start_datetime=utcnow() + timedelta(days=30),
                end_datetime=utcnow() + timedelta(days=30, hours=2),
            )
            db.session.add(booking)
            db.session.commit()
            booking_id = booking.id

        response = client.post(
            f"/api/venues/bookings/{booking_id}/cancel",
            headers=auth_header("venue-staff@test.com"),
            json={"reason": "Venue maintenance"},
        )

        assert response.status_code == 200
        assert response.get_json()["status"] == "cancelled"
        with client.application.app_context():
            assert db.session.get(Event, event_id).status == "planning"


# =====================================================================
# Story 4: Retain rejected and cancelled requests with final status visible
# =====================================================================

class TestStory4Visibility:
    @pytest.mark.parametrize("status", ["rejected", "cancelled"])
    @pytest.mark.parametrize("role", ["event_coordinator", "venue_staff", "technical_support_staff", "safety_officer"])
    def test_internal_staff_see_rejected_and_cancelled_events_with_final_status(
        self, client, auth_header, organiser, make_user, make_event, role, status
    ):
        # AC1: any internal role sees a rejected/cancelled event on the
        # combined planning list, with its final status intact.
        make_user(f"{role}-{status}@x.com", [role])
        event_id = make_event(organiser, status=status, name=f"Event {status}")

        res = client.get("/api/events", headers=auth_header(f"{role}-{status}@x.com"))
        assert res.status_code == 200
        rows = {e["id"]: e["status"] for e in res.get_json()}
        assert rows[event_id] == status

    @pytest.mark.parametrize("status", ["rejected", "cancelled"])
    def test_organiser_sees_own_rejected_or_cancelled_event_in_their_list(
        self, client, auth_header, organiser, make_event, status
    ):
        # AC1: the Organiser's own list keeps showing their closed-out event.
        event_id = make_event(organiser, status=status, name=f"Event {status}")
        rows = {r["id"]: r["status"] for r in _mine(client, auth_header(ORG)).get_json()}
        assert rows[event_id] == status

    @pytest.mark.parametrize("status", ["rejected", "cancelled"])
    def test_unrelated_organiser_and_attendee_cannot_view_closed_event(
        self, client, auth_header, organiser, make_user, make_event, status
    ):
        # AC2: a user with no association to the event gets ordinary
        # per-role visibility rules -- not access just because it's closed.
        make_user("other-org@test.com", ["event_organiser"])
        make_user("att@test.com", ["attendee"])
        event_id = make_event(organiser, status=status)

        for email in ("other-org@test.com", "att@test.com"):
            res = _get(client, auth_header(email), event_id)
            assert res.status_code == 404

    @pytest.mark.parametrize("status", ["rejected", "cancelled"])
    def test_cannot_edit_closed_event_via_draft_route(
        self, client, auth_header, organiser, make_event, status
    ):
        # AC3: the only write path for core fields (PUT /drafts/<id>)
        # refuses a non-draft event, terminal or not.
        event_id = make_event(organiser, status=status, name="Original Name")
        res = client.put(
            f"/api/events/drafts/{event_id}",
            headers=auth_header(ORG),
            json={"name": "Changed Name"},
        )
        assert res.status_code == 400
        with client.application.app_context():
            assert db.session.get(Event, event_id).name == "Original Name"

    def test_resubmission_keeps_original_rejected_event_independently_searchable(
        self, client, auth_header, organiser, coordinator, make_event
    ):
        # AC5: after resubmitting a rejected request, the original is
        # still present and still "rejected" in the Organiser's list,
        # alongside the new resubmission as a separate row.
        original_id = make_event(
        organiser,
        status="rejected",
        name="Original Request",
        purpose="Purpose",
        description="Description",
        proposed_date=date(2026, 12, 1),
        proposed_time=time(9, 0),
        expected_attendance=50,
        capacity_needed=100,
        required_layout="theatre",
        accessibility_needs="None",
        coordinator_id=coordinator,
        )

        res = client.post(
            f"/api/events/{original_id}/resubmit",
            headers=auth_header(ORG),
            json={},
        )
        assert res.status_code == 201, res.get_json()
        new_id = res.get_json()["id"]

        rows = {r["id"]: r["status"] for r in _mine(client, auth_header(ORG)).get_json()}
        assert rows[original_id] == "rejected"
        assert new_id in rows
        assert new_id != original_id