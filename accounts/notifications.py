"""Helpers to create role-targeted notification alerts for the bell icon."""
from .models import Notification, CustomUser, Employee

# Staff job types that map to Employee.job_type
STAFF_JOBS = {'manager', 'receptionist', 'kitchen', 'bar', 'housekeeping'}


def _recipients_for_roles(roles, branch=None, exclude_user=None):
    """
    Resolve a set of users for the given roles.
    roles may include 'admin' plus any Employee job types.
    When `branch` is given, staff are limited to that branch (or staff with no
    branch); admins always receive the alert.
    """
    users = {}

    if 'admin' in roles:
        for u in CustomUser.objects.filter(role='admin', is_active=True):
            users[u.id] = u

    job_roles = [r for r in roles if r in STAFF_JOBS]
    if job_roles:
        qs = Employee.objects.filter(job_type__in=job_roles, user__is_active=True).select_related('user')
        if branch is not None:
            from django.db.models import Q
            qs = qs.filter(Q(branch=branch) | Q(branch__isnull=True))
        for e in qs:
            users[e.user_id] = e.user

    if exclude_user and exclude_user.id in users:
        del users[exclude_user.id]

    return list(users.values())


def notify_roles(roles, notif_type, title, body='', link='', branch=None, exclude_user=None, dedupe=False):
    recipients = _recipients_for_roles(roles, branch=branch, exclude_user=exclude_user)
    objs = []
    for u in recipients:
        if dedupe and Notification.objects.filter(
            recipient=u, notif_type=notif_type, title=title, is_read=False
        ).exists():
            continue
        objs.append(Notification(recipient=u, notif_type=notif_type, title=title, body=body, link=link))
    if objs:
        Notification.objects.bulk_create(objs)
    return len(objs)


def notify_user(user, notif_type, title, body='', link=''):
    if not user:
        return None
    return Notification.objects.create(
        recipient=user, notif_type=notif_type, title=title, body=body, link=link
    )
