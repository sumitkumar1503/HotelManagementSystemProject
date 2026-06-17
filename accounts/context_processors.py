from .models import SiteSetting, Message, Branch, Booking


def _default_branch():
    """The hotel's primary branch — first active one, else the first created."""
    return (Branch.objects.filter(is_active=True).order_by('id').first()
            or Branch.objects.order_by('id').first())


def _display_branch(request):
    """
    Decide which branch's identity (name / logo / address) should be shown to
    the current user:
      - admin / manager  -> the branch they are currently managing (session), else default
      - other staff      -> their own assigned branch, else default
      - customer         -> the branch of their most recent booking, else default
      - anonymous        -> the default branch
    """
    user = getattr(request, 'user', None)

    # Admin / manager use the branch they switched to.
    if user is not None and user.is_authenticated:
        active_id = request.session.get('active_branch_id')
        if user.role == 'admin':
            if active_id:
                b = Branch.objects.filter(id=active_id).first()
                if b:
                    return b
            return _default_branch()

        if user.role == 'employee' and hasattr(user, 'employee_profile'):
            emp = user.employee_profile
            if emp.job_type == 'manager':
                if active_id:
                    b = Branch.objects.filter(id=active_id).first()
                    if b:
                        return b
                return _default_branch()
            # Front-line staff: identity follows the branch they work at.
            return emp.branch or _default_branch()

        if user.role == 'customer':
            last = (Booking.objects.filter(user=user, branch__isnull=False)
                    .order_by('-id').values_list('branch_id', flat=True).first())
            if last:
                b = Branch.objects.filter(id=last).first()
                if b:
                    return b
            return _default_branch()

    return _default_branch()


def site_globals(request):
    """Expose currency/VAT, hotel identity (per active branch), unread messages and branch list."""
    ctx = {
        'site_currency': '$',
        'site_currency_code': 'USD',
        'site_vat': 0,
        'site_hotel_name': 'Grand Hotel',
        'site_hotel_logo': '',
        'site_hotel_address': '',
        'site_hotel_phone': '',
        'site_hotel_email': '',
    }

    # Currency / VAT / fallback identity are global (Site Settings).
    try:
        settings_obj = SiteSetting.load()
        ctx.update({
            'site_currency': settings_obj.currency_symbol,
            'site_currency_code': settings_obj.currency_code,
            'site_vat': settings_obj.vat_percentage,
            'site_hotel_name': settings_obj.hotel_name,
            'site_hotel_logo': settings_obj.hotel_logo.url if settings_obj.hotel_logo else '',
            'site_hotel_address': settings_obj.hotel_address,
            'site_hotel_phone': settings_obj.hotel_phone,
            'site_hotel_email': settings_obj.hotel_email,
        })
    except Exception:
        # Table may not exist yet (e.g. before migrations run).
        pass

    # Hotel identity is per-branch: override the global defaults with the
    # branch the current user is viewing.
    try:
        branch = _display_branch(request)
        if branch:
            ctx['site_hotel_name'] = branch.name or ctx['site_hotel_name']
            if branch.logo:
                ctx['site_hotel_logo'] = branch.logo.url
            ctx['site_hotel_address'] = branch.address or ctx['site_hotel_address']
            ctx['site_hotel_phone'] = branch.phone or ctx['site_hotel_phone']
            ctx['site_hotel_email'] = branch.email or ctx['site_hotel_email']
    except Exception:
        pass

    if request.user.is_authenticated:
        try:
            ctx['unread_messages'] = Message.objects.filter(recipient=request.user, is_read=False).count()
        except Exception:
            ctx['unread_messages'] = 0

        # Active branch (for admin/manager branch switching)
        try:
            active_branch_id = request.session.get('active_branch_id')
            if active_branch_id:
                ctx['active_branch'] = Branch.objects.filter(id=active_branch_id).first()
            ctx['all_branches'] = Branch.objects.filter(is_active=True)
        except Exception:
            pass

    return ctx
