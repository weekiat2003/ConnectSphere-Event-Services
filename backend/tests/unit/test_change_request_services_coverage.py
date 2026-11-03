"""Cover validation, dry-run and legacy change-application helper paths."""
from contextlib import nullcontext
from datetime import date, time, timedelta
from types import SimpleNamespace as NS
from unittest.mock import MagicMock
import pytest
from app.change_requests import services as s

@pytest.mark.parametrize('cleaner,value', [(s.CLEANERS['name'], 123), (s._clean_date, 'bad'), (s._clean_date, None), (s._clean_date, date.today() - timedelta(days=1)), (s._clean_time, 'bad'), (s._clean_time, None), (s._clean_bool, 'yes'), (s._clean_facilities, 'WiFi'), (s._clean_facilities, [123]), (s._clean_venue, True), (s._clean_venue, '1'), (s._clean_equipment, {}), (s._clean_equipment, [{'type': 'Mic', 'quantity': True}])])
def test_invalid_cleaners(cleaner, value):
    with pytest.raises(ValueError):
        cleaner(value)

def test_clean_facilities():
    assert s._clean_facilities([' WiFi ', '', '  ', 'Projector']) == ['WiFi', 'Projector']

@pytest.mark.parametrize('venue', [None, NS(is_active=False)])
def test_unavailable_venue(monkeypatch, venue):
    session = MagicMock()
    session.get.return_value = venue
    monkeypatch.setattr(s, 'db', NS(session=session))
    with pytest.raises(ValueError, match='not available'):
        s._clean_venue(1)

@pytest.mark.parametrize('field,value,expected', [('proposed_date', date(2030, 1, 2), '2030-01-02'), ('proposed_date', None, None), ('proposed_time', time(9, 30), '09:30:00'), ('proposed_time', None, None), ('proposed_end_date', date(2030, 1, 3), '2030-01-03'), ('proposed_end_date', None, None), ('proposed_end_time', time(17), '17:00:00'), ('proposed_end_time', None, None), ('required_facilities', None, []), ('registration_required', True, True), ('registration_required', None, False)])
def test_current_values(field, value, expected):
    assert s._current_value(NS(**{field: value}), field) == expected

@pytest.mark.parametrize('venue_id', [None, 42])
def test_current_venue(monkeypatch, venue_id):
    query = MagicMock()
    query.filter_by.return_value.order_by.return_value.first.return_value = None if venue_id is None else NS(venue_id=venue_id)
    monkeypatch.setattr(s, 'VenueBooking', NS(query=query, start_datetime=MagicMock()))
    assert s.current_venue_id(NS(id=7)) == venue_id

def test_unknown_stored_field():
    cleaned, errors = s._revalidate({'unsupported': {'to': 'value'}})
    assert cleaned == {} and 'cannot be changed' in errors['unsupported']

@pytest.mark.parametrize('field', sorted(s.CLEARABLE_FIELDS))
def test_clearable_stored_field(field):
    assert s._revalidate({field: {'to': None}}) == ({field: None}, {})

def test_malformed_stored_field():
    cleaned, errors = s._revalidate({'name': 'malformed'})
    assert cleaned == {} and 'name' in errors

@pytest.mark.parametrize('status', ['processed', 'pending'])
def test_rejection_guards(monkeypatch, status):
    request = NS(status=status, coordinator_id=None, decision_reason=None, decided_at=None)
    monkeypatch.setattr(s, '_get_locked_request', lambda _: request)
    monkeypatch.setattr(s, '_assert_assigned_coordinator', MagicMock())
    session = MagicMock()
    monkeypatch.setattr(s, 'db', NS(session=session))
    notify = MagicMock()
    monkeypatch.setattr(s.notifications, 'notify_organiser_of_change_request', notify)
    if status == 'processed':
        with pytest.raises(s.ChangeRequestError, match='Only a pending'):
            s.reject_change_request(10, 20, 'The proposed change is unsuitable.')
    else:
        assert s.reject_change_request(10, 20, 'The proposed change is unsuitable.', dry_run=True) is request
        assert request.status == 'pending'
        assert request.coordinator_id is request.decision_reason is request.decided_at is None
    session.commit.assert_not_called()
    notify.assert_not_called()

@pytest.mark.parametrize('field,value,expected', [('proposed_date', '2030-01-02', date(2030, 1, 2)), ('proposed_end_date', '2030-01-03', date(2030, 1, 3)), ('proposed_time', '09:30:00', time(9, 30)), ('proposed_end_time', '17:00:00', time(17)), ('proposed_date', date(2030, 1, 2), date(2030, 1, 2)), ('proposed_time', time(9, 30), time(9, 30)), ('proposed_end_date', None, None), ('name', 'Conference', 'Conference')])
def test_python_value(field, value, expected):
    assert s._python_value(field, value) == expected

@pytest.mark.parametrize('empty', [True, False])
def test_replace_equipment(monkeypatch, empty):
    event = NS(id=7, equipment_requirements=[] if empty else [NS(id=1, equipment_type=' Microphone '), NS(id=2, equipment_type='Speaker'), NS(id=3, equipment_type='Projector'), NS(id=4, equipment_type=None)])
    reservations = [] if empty else [NS(equipment_requirement_id=i, quantity=q, status='reserved') for i, q in [(1, 2), (2, 5), (3, 1), (4, 1), (999, 1)]]
    query = MagicMock()
    query.filter_by.return_value.all.return_value = reservations
    monkeypatch.setattr(s, 'EquipmentReservation', NS(query=query, start_datetime=MagicMock()))
    ids = iter(range(100, 110))
    monkeypatch.setattr(s, 'EventEquipmentRequirement', lambda **kw: NS(id=next(ids), needs_recheck=False, **kw))
    session = MagicMock()
    monkeypatch.setattr(s, 'db', NS(session=session))
    items = [] if empty else [{'type': ' Microphone ', 'quantity': 3, 'technicalNotes': 'Wireless'}, {'type': 'Speaker', 'quantity': 2}]
    s._replace_equipment_requirements(event, items)
    session.flush.assert_called_once()
    if empty:
        assert event.equipment_requirements == []
    else:
        mic, speaker = event.equipment_requirements
        assert mic.equipment_type == 'Microphone' and mic.technical_notes == 'Wireless'
        assert speaker.technical_notes is None
        assert reservations[0].equipment_requirement_id == mic.id
        assert reservations[0].status == 'reserved'
        assert all((r.status == 'released' for r in reservations[1:]))
        assert speaker.needs_recheck is True and speaker.status == 'requested'

@pytest.mark.parametrize('field,current,proposed', [('name', 'Old name', 'New name'), ('venue_id', 1, 2), ('equipment_requirements', [], [{'type': 'Mic', 'quantity': 2}])])
def test_apply_cleaned(monkeypatch, field, current, proposed):
    session = MagicMock()
    monkeypatch.setattr(s, 'db', NS(session=session))
    monkeypatch.setattr(s, 'EventChangeHistory', NS)
    replace = MagicMock()
    monkeypatch.setattr(s, '_replace_equipment_requirements', replace)
    event = NS(id=7, **{field: current})
    s._apply_cleaned_change(event, NS(id=10), field, current, proposed, 20)
    session.add.assert_called_once()
    assert vars(session.add.call_args.args[0]) == dict(event_id=7, change_request_id=10, field=field, old_value=current, new_value=proposed, changed_by=20)
    if field == 'equipment_requirements':
        replace.assert_called_once_with(event, proposed)
    elif field == 'venue_id':
        assert event.venue_id == current
        replace.assert_not_called()
    else:
        assert event.name == proposed
        replace.assert_not_called()

def test_planned_updates_ignores_unchanged(monkeypatch):
    monkeypatch.setattr(s, 'db', NS(session=NS(no_autoflush=nullcontext())))
    event = NS(name='Annual Conference')
    assert s._planned_updates(event, {'name': {'from': 'Old name', 'to': event.name}}) == []
    assert event.name == 'Annual Conference'

@pytest.mark.parametrize('count', [0, 2])
def test_cancelled_event_resolves_pending_withdrawals(monkeypatch, count):
    requests = [NS(status='pending', coordinator_id=None, decided_at=None,
                   decision_reason=None) for _ in range(count)]
    query = MagicMock()
    query.filter_by.return_value.all.return_value = requests
    monkeypatch.setattr(s, 'ChangeRequest', NS(query=query))
    now = object()
    monkeypatch.setattr(s, 'utcnow', lambda: now)
    result = s.resolve_withdrawals_for_cancelled_event(NS(id=7), 20, 'Event cancelled')
    assert result is requests
    query.filter_by.assert_called_once_with(event_id=7, request_type='withdrawal', status='pending')
    for request in requests:
        assert request.status == 'processed'
        assert request.coordinator_id == 20
        assert request.decided_at is now
        assert request.decision_reason == 'Event cancelled'
