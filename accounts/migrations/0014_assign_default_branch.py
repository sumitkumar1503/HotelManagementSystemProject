from django.db import migrations


def assign_default_branch(apps, schema_editor):
    """
    Existing rooms / bookings / staff / menu items created before the multi-branch
    feature have no branch. Attach them to the default (first) branch so they remain
    visible once branch scoping is active. New branches start empty for fresh setup.
    """
    Branch = apps.get_model('accounts', 'Branch')
    default = Branch.objects.filter(is_active=True).order_by('id').first() or Branch.objects.order_by('id').first()
    if not default:
        return  # No branches yet; nothing to assign.

    for model_name in ('Room', 'Booking', 'Employee', 'FoodItem', 'Drink'):
        Model = apps.get_model('accounts', model_name)
        Model.objects.filter(branch__isnull=True).update(branch=default)


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0013_branch_logo_fooditem_branch'),
    ]

    operations = [
        migrations.RunPython(assign_default_branch, noop),
    ]
