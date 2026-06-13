from .models import SiteSetting, Message, Branch


def site_globals(request):
    """Expose currency/VAT, unread message count and branch info to all templates."""
    ctx = {
        'site_currency': '$',
        'site_currency_code': 'USD',
        'site_vat': 0,
        'site_hotel_name': 'Grand Hotel',
    }

    try:
        settings_obj = SiteSetting.load()
        ctx.update({
            'site_currency': settings_obj.currency_symbol,
            'site_currency_code': settings_obj.currency_code,
            'site_vat': settings_obj.vat_percentage,
            'site_hotel_name': settings_obj.hotel_name,
        })
    except Exception:
        # Table may not exist yet (e.g. before migrations run).
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
