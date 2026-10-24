"""Shared notification plumbing used by every trigger in triggers.py.

Transaction rule: notify() / notify_users() / notify_role() only *add* rows to
the session — they never commit. The calling service commits as part of its
own action, so a notification is saved if and only if the action it describes
is saved. (If the action rolls back, no misleading notification is left.)
"""
from app.common.time import utcnow
from app.extensions import db
from app.models.notification import NOTIFICATION_TYPES, Notification
from app.models.user import Role, User


class NotificationError(ValueError):
    pass


# ---------------------------------------------------------------------------
# Creating notifications (called from triggers.py)
# ---------------------------------------------------------------------------

def notify(recipient_id: int, type_: str, title: str, message: str,
           event_id: int = None, link: str = None, data: dict = None) -> Notification:
    """Queue one notification for one user. Does NOT commit."""
    if type_ not in NOTIFICATION_TYPES:
        raise NotificationError(f"Unknown notification type: {type_}")
    if not title or not message:
        raise NotificationError("A notification needs a title and a message")

    notification = Notification(
        recipient_id=recipient_id,
        type=type_,
        title=title,
        message=message,
        event_id=event_id,
        link=link,
        data=data,
    )
    db.session.add(notification)
    return notification


def notify_users(recipient_ids, type_: str, title: str, message: str,
                 event_id: int = None, link: str = None, data: dict = None) -> list[Notification]:
    """Same message to several users. Each user gets exactly one, even if they
    appear twice (e.g. hold two roles). Does NOT commit."""
    unique_ids = list(dict.fromkeys(i for i in recipient_ids if i is not None))
    return [notify(i, type_, title, message, event_id, link, data) for i in unique_ids]


def active_user_ids_with_role(role_name: str) -> list[int]:
    rows = (
        db.session.query(User.id)
        .join(User.roles)
        .filter(Role.name == role_name, User.is_active.is_(True))
        .order_by(User.id)
        .all()
    )
    return [r.id for r in rows]


def notify_role(role_name: str, type_: str, title: str, message: str,
                event_id: int = None, link: str = None, data: dict = None) -> list[Notification]:
    """Broadcast to every active user holding a role. Does NOT commit."""
    return notify_users(active_user_ids_with_role(role_name), type_, title, message, event_id, link, data)


def clear_notifications(type_: str, event_id: int, extra_data: dict = None) -> int:
    """Mark every uncleared notification of `type_` about `event_id` as cleared
    (and read), merging `extra_data` into each one's data. Does NOT commit."""
    now = utcnow()
    rows = Notification.query.filter_by(type=type_, event_id=event_id, cleared_at=None).all()
    for n in rows:
        n.cleared_at = now
        if not n.is_read:
            n.is_read = True
            n.read_at = now
        if extra_data:
            n.data = {**(n.data or {}), **extra_data}
    return len(rows)


# ---------------------------------------------------------------------------
# Reading / marking (called from routes.py — these DO commit)
# ---------------------------------------------------------------------------

def list_for_user(user_id: int, unread_only: bool = False, limit: int = 50) -> list[Notification]:
    query = Notification.query.filter_by(recipient_id=user_id)
    if unread_only:
        query = query.filter_by(is_read=False)
    return query.order_by(Notification.created_at.desc(), Notification.id.desc()).limit(limit).all()


def unread_count(user_id: int) -> int:
    return Notification.query.filter_by(recipient_id=user_id, is_read=False).count()


def mark_read(notification_id: int, user_id: int) -> Notification:
    notification = db.session.get(Notification, notification_id)
    if notification is None:
        raise LookupError("Notification not found")
    if notification.recipient_id != user_id:
        # Treated as "not found" by the route so ids of others' notifications don't leak.
        raise PermissionError("Not your notification")
    if not notification.is_read:
        notification.is_read = True
        notification.read_at = utcnow()
        db.session.commit()
    return notification


def mark_all_read(user_id: int) -> int:
    now = utcnow()
    count = (
        Notification.query
        .filter_by(recipient_id=user_id, is_read=False)
        .update({"is_read": True, "read_at": now}, synchronize_session=False)
    )
    db.session.commit()
    return count
