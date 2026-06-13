from django.contrib import admin
from .models import PaymentSetting, PaymentReceipt


@admin.register(PaymentSetting)
class PaymentSettingAdmin(admin.ModelAdmin):
    list_display = ('bank_name', 'account_holder_name', 'account_number', 'updated_at')


@admin.register(PaymentReceipt)
class PaymentReceiptAdmin(admin.ModelAdmin):
    list_display = ('booking', 'amount', 'status', 'uploaded_at')
    list_filter = ('status',)
    search_fields = ('booking__id', 'note')
