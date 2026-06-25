"""Lightweight helper for creating audit log entries.

Usage from any view:
    from accounts.audit import log_action
    log_action(request, action='create', module='Drink',
               summary='Created drink Coca Cola', object=drink)
"""
from .models import AuditLog


def _client_ip(request):
    if request is None:
        return None
    xff = request.META.get('HTTP_X_FORWARDED_FOR')
    if xff:
        return xff.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR')


def log_action(request, *, action, module, summary, object=None, branch=None):
    """
    Record an action by the current staff user.

    `request` may be None for system-level actions; in that case `branch`
    should be supplied explicitly when possible.
    """
    user = getattr(request, 'user', None) if request is not None else None
    if user is not None and not getattr(user, 'is_authenticated', False):
        user = None

    obj_repr = ''
    obj_id = ''
    if object is not None:
        try:
            obj_repr = str(object)[:120]
        except Exception:
            obj_repr = object.__class__.__name__
        try:
            obj_id = str(object.pk)
        except Exception:
            obj_id = ''

    try:
        AuditLog.objects.create(
            user=user,
            action=action or 'other',
            module=module or '',
            summary=summary[:255] if summary else '',
            object_repr=obj_repr,
            object_id=obj_id,
            branch=branch,
            ip_address=_client_ip(request),
        )
    except Exception:
        # Never let auditing break the actual request flow.
        pass
