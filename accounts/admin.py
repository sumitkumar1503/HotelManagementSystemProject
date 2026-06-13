from django.contrib import admin
from .models import (
    PaymentSetting, PaymentReceipt, Branch, Wallet, WalletTransaction,
    Drink, BarOrder, BarOrderItem, StockTransaction, Message, SiteSetting,
)


@admin.register(PaymentSetting)
class PaymentSettingAdmin(admin.ModelAdmin):
    list_display = ('bank_name', 'account_holder_name', 'account_number', 'updated_at')


@admin.register(PaymentReceipt)
class PaymentReceiptAdmin(admin.ModelAdmin):
    list_display = ('booking', 'amount', 'status', 'uploaded_at')
    list_filter = ('status',)
    search_fields = ('booking__id', 'note')


@admin.register(Branch)
class BranchAdmin(admin.ModelAdmin):
    list_display = ('name', 'code', 'city', 'is_active')
    list_filter = ('is_active',)


@admin.register(Wallet)
class WalletAdmin(admin.ModelAdmin):
    list_display = ('user', 'balance')


@admin.register(WalletTransaction)
class WalletTransactionAdmin(admin.ModelAdmin):
    list_display = ('wallet', 'txn_type', 'amount', 'created_at')
    list_filter = ('txn_type',)


@admin.register(Drink)
class DrinkAdmin(admin.ModelAdmin):
    list_display = ('name', 'category', 'price', 'stock_quantity', 'is_available', 'branch')
    list_filter = ('category', 'is_available', 'branch')


class BarOrderItemInline(admin.TabularInline):
    model = BarOrderItem
    extra = 0


@admin.register(BarOrder)
class BarOrderAdmin(admin.ModelAdmin):
    list_display = ('id', 'booking', 'total_price', 'status', 'is_paid', 'created_at')
    list_filter = ('status', 'is_paid')
    inlines = [BarOrderItemInline]


@admin.register(StockTransaction)
class StockTransactionAdmin(admin.ModelAdmin):
    list_display = ('drink', 'quantity', 'note', 'created_at')


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ('sender', 'recipient', 'subject', 'is_read', 'created_at')
    list_filter = ('is_read',)


@admin.register(SiteSetting)
class SiteSettingAdmin(admin.ModelAdmin):
    list_display = ('hotel_name', 'currency_code', 'currency_symbol', 'vat_percentage')
