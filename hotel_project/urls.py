from django.contrib import admin
from django.urls import path
from django.contrib.auth.views import LogoutView
from accounts import views
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('', views.index, name='home'),
    path('about/', views.about_us, name='about'),
    path('login/', views.login_view, name='login'),
    path('signup/', views.register_customer, name='signup'),
    path('logout/', LogoutView.as_view(next_page='home'), name='logout'),
    path('rooms/', views.room_list, name='room_list'), # New Page
    path('book-room/<int:room_id>/', views.book_room, name='book_room'), 
    path('dashboard/bookings/', views.view_bookings, name='view_bookings'),
    path('dashboard/booking/check-in/<int:booking_id>/', views.staff_check_in, name='staff_check_in'),
    path('dashboard/booking/check-out/<int:booking_id>/', views.staff_check_out, name='staff_check_out'),
    path('dashboard/admin/', views.admin_dashboard, name='admin_dashboard'),
    path('dashboard/admin/add-employee/', views.add_employee, name='add_employee'),
    path('dashboard/admin/employees/', views.view_employees, name='view_employees'),
    path('dashboard/admin/employee/edit/<int:employee_id>/', views.edit_employee, name='edit_employee'),
    path('dashboard/admin/employee/delete/<int:employee_id>/', views.delete_employee, name='delete_employee'),
    path('dashboard/admin/rooms/', views.view_rooms, name='view_rooms'),
    path('dashboard/admin/rooms/add/', views.add_room, name='add_room'),
    path('dashboard/admin/rooms/edit/<int:room_id>/', views.edit_room, name='edit_room'),
    path('dashboard/admin/rooms/delete/<int:room_id>/', views.delete_room, name='delete_room'),
    path('dashboard/admin/guests/', views.view_guests, name='view_guests'),
    path('dashboard/admin/guests/edit/<int:guest_id>/', views.edit_guest, name='edit_guest'),
    path('dashboard/admin/guests/delete/<int:guest_id>/', views.delete_guest, name='delete_guest'),
    path('dashboard/admin/cleaning-logs/', views.view_cleaning_logs, name='view_cleaning_logs'),
    path('dashboard/admin/food/', views.view_food_menu, name='view_food_menu'),
    path('dashboard/admin/food/add/', views.add_food_item, name='add_food_item'),
    path('dashboard/admin/food/edit/<int:item_id>/', views.edit_food_item, name='edit_food_item'),
    path('dashboard/admin/food/delete/<int:item_id>/', views.delete_food_item, name='delete_food_item'),
    path('dashboard/admin/kitchen-monitor/', views.admin_kitchen_monitor, name='admin_kitchen_monitor'),
    path('dashboard/admin/kitchen-history/', views.admin_kitchen_history, name='admin_kitchen_history'),
    # Receptionist Staff
    path('dashboard/receptionist/', views.receptionist_dashboard, name='receptionist_dashboard'),
    path('dashboard/receptionist/walk-in/', views.receptionist_walkin, name='receptionist_walkin'), # NEW
    path('dashboard/receptionist/rooms/', views.receptionist_room_status, name='receptionist_room_status'), # NEW
    path('dashboard/receptionist/guests/', views.receptionist_guest_list, name='receptionist_guest_list'), # NEW
    path('dashboard/receptionist/invoice/<int:booking_id>/', views.generate_invoice, name='generate_invoice'),
    path('dashboard/receptionist/pay/<int:booking_id>/', views.process_checkout_payment, name='process_checkout_payment'),
    path('dashboard/receptionist/payments/', views.pending_payments, name='pending_payments'),
    path('dashboard/receptionist/payments/confirm/<int:receipt_id>/', views.confirm_payment, name='confirm_payment'),
    path('dashboard/receptionist/payments/reject/<int:receipt_id>/', views.reject_payment, name='reject_payment'),

    # Admin Payment Settings
    path('dashboard/admin/payment-settings/', views.payment_settings, name='payment_settings'),
    path('dashboard/admin/site-settings/', views.site_settings, name='site_settings'),
    path('dashboard/admin/site-content/', views.site_content, name='site_content'),
    path('dashboard/admin/guests/<int:guest_id>/add-credit/', views.add_wallet_credit, name='add_wallet_credit'),

    # Room image gallery (Admin)
    path('dashboard/admin/rooms/<int:room_id>/images/', views.manage_room_images, name='manage_room_images'),
    path('dashboard/admin/rooms/images/delete/<int:image_id>/', views.delete_room_image, name='delete_room_image'),

    # Kitchen ingredient inventory
    path('dashboard/kitchen/inventory/', views.ingredient_inventory, name='ingredient_inventory'),
    path('dashboard/kitchen/inventory/add/', views.add_ingredient, name='add_ingredient'),
    path('dashboard/kitchen/inventory/edit/<int:ingredient_id>/', views.edit_ingredient, name='edit_ingredient'),
    path('dashboard/kitchen/inventory/delete/<int:ingredient_id>/', views.delete_ingredient, name='delete_ingredient'),
    path('dashboard/kitchen/inventory/restock/<int:ingredient_id>/', views.restock_ingredient, name='restock_ingredient'),
    path('dashboard/kitchen/inventory/export/', views.export_ingredients_csv, name='export_ingredients_csv'),
    path('dashboard/kitchen/inventory/template/', views.ingredient_csv_template, name='ingredient_csv_template'),
    path('dashboard/kitchen/inventory/import/', views.import_ingredients_csv, name='import_ingredients_csv'),

    # Bar CSV import/export
    path('dashboard/bar/inventory/export/', views.export_drinks_csv, name='export_drinks_csv'),
    path('dashboard/bar/inventory/template/', views.drink_csv_template, name='drink_csv_template'),
    path('dashboard/bar/inventory/import/', views.import_drinks_csv, name='import_drinks_csv'),

    # Laundry module
    path('dashboard/customer/order-laundry/', views.order_laundry, name='order_laundry'),
    path('dashboard/customer/laundry-orders/', views.customer_laundry_history, name='customer_laundry_history'),
    path('dashboard/customer/laundry/pay/<int:order_id>/', views.pay_laundry_wallet, name='pay_laundry_wallet'),
    path('dashboard/laundry/', views.laundry_monitor, name='laundry_monitor'),
    path('dashboard/laundry/status/<int:order_id>/<str:status>/', views.update_laundry_status, name='update_laundry_status'),
    path('dashboard/laundry/paid/<int:order_id>/', views.mark_laundry_paid, name='mark_laundry_paid'),
    path('dashboard/admin/laundry-services/', views.laundry_services, name='laundry_services'),
    path('dashboard/admin/laundry-services/add/', views.add_laundry_service, name='add_laundry_service'),
    path('dashboard/admin/laundry-services/edit/<int:service_id>/', views.edit_laundry_service, name='edit_laundry_service'),
    path('dashboard/admin/laundry-services/delete/<int:service_id>/', views.delete_laundry_service, name='delete_laundry_service'),

    # Notifications
    path('notifications/', views.notifications_page, name='notifications_page'),
    path('notifications/feed/', views.notifications_feed, name='notifications_feed'),
    path('notifications/read-all/', views.mark_notifications_read, name='mark_notifications_read'),
    path('notifications/open/<int:notif_id>/', views.open_notification, name='open_notification'),

    # Expenses (Admin + Manager)
    path('dashboard/expenses/', views.expense_list, name='expense_list'),
    path('dashboard/expenses/add/', views.add_expense, name='add_expense'),
    path('dashboard/expenses/edit/<int:expense_id>/', views.edit_expense, name='edit_expense'),
    path('dashboard/expenses/delete/<int:expense_id>/', views.delete_expense, name='delete_expense'),

    # Accounting & Report (Admin + Manager)
    path('dashboard/accounting/', views.accounting_report, name='accounting_report'),

    # Global Search
    path('dashboard/search/', views.global_search, name='global_search'),

    # Multi-branch Management (Admin / Manager)
    path('dashboard/branches/', views.manage_branches, name='manage_branches'),
    path('dashboard/branches/add/', views.add_branch, name='add_branch'),
    path('dashboard/branches/edit/<int:branch_id>/', views.edit_branch, name='edit_branch'),
    path('dashboard/branches/delete/<int:branch_id>/', views.delete_branch, name='delete_branch'),
    path('dashboard/branches/switch/<int:branch_id>/', views.switch_branch, name='switch_branch'),
    path('dashboard/manager/', views.manager_dashboard, name='manager_dashboard'),

    # In-app Messaging (all users)
    path('messages/', views.inbox, name='inbox'),
    path('messages/sent/', views.sent_messages, name='sent_messages'),
    path('messages/compose/', views.compose_message, name='compose_message'),
    path('messages/<int:message_id>/', views.view_message, name='view_message'),
    path('messages/<int:message_id>/reply/', views.reply_message, name='reply_message'),
    path('messages/<int:message_id>/delete/', views.delete_message, name='delete_message'),

    # Bar - Staff
    path('dashboard/bar/', views.bar_dashboard, name='bar_dashboard'),
    path('dashboard/bar/status/<int:order_id>/<str:status>/', views.update_bar_order_status, name='update_bar_order_status'),
    path('dashboard/bar/history/', views.bar_history, name='bar_history'),
    path('dashboard/bar/inventory/', views.bar_inventory, name='bar_inventory'),
    path('dashboard/bar/inventory/add/', views.add_drink, name='add_drink'),
    path('dashboard/bar/inventory/edit/<int:drink_id>/', views.edit_drink, name='edit_drink'),
    path('dashboard/bar/inventory/delete/<int:drink_id>/', views.delete_drink, name='delete_drink'),
    path('dashboard/bar/inventory/restock/<int:drink_id>/', views.restock_drink, name='restock_drink'),
    path('dashboard/bar/profile/', views.bar_profile, name='bar_profile'),

    # Sales Record (Kitchen + Bar)
    path('dashboard/sales/', views.sales_record, name='sales_record'),
    path('dashboard/sales/food-paid/<int:order_id>/', views.mark_food_paid, name='mark_food_paid'),
    path('dashboard/sales/bar-paid/<int:order_id>/', views.mark_bar_paid, name='mark_bar_paid'),

    # Customer Staff
    path('dashboard/customer/', views.customer_dashboard, name='customer_dashboard'),
    path('dashboard/my-bookings/', views.customer_bookings, name='customer_bookings'),
    path('dashboard/customer/order-food/', views.order_food, name='order_food'),
    path('dashboard/customer/food-orders/', views.customer_food_history, name='customer_food_history'),
    path('dashboard/customer/profile/', views.customer_profile, name='customer_profile'),
    path('dashboard/customer/pay/<int:booking_id>/', views.pay_booking, name='pay_booking'),
    path('dashboard/customer/pay/<int:booking_id>/wallet/', views.pay_booking_wallet, name='pay_booking_wallet'),
    path('dashboard/customer/receipt/edit/<int:receipt_id>/', views.edit_receipt, name='edit_receipt'),
    path('dashboard/customer/receipt/delete/<int:receipt_id>/', views.delete_receipt, name='delete_receipt'),
    path('dashboard/customer/order-drinks/', views.order_drinks, name='order_drinks'),
    path('dashboard/customer/bar-orders/', views.customer_bar_history, name='customer_bar_history'),
    path('dashboard/customer/wallet/', views.customer_wallet, name='customer_wallet'),
    path('dashboard/customer/cancel/<int:booking_id>/', views.cancel_booking, name='cancel_booking'),


    # Kitchen Staff
    path('dashboard/kitchen/', views.kitchen_dashboard, name='kitchen_dashboard'),
    path('dashboard/kitchen/status/<int:order_id>/<str:status>/', views.update_order_status, name='update_order_status'),
    path('dashboard/kitchen/history/', views.kitchen_history, name='kitchen_history'), 
    path('dashboard/kitchen/profile/', views.kitchen_profile, name='kitchen_profile'), 
    
    # Housekeeping Staff
    path('dashboard/housekeeping/', views.housekeeping_dashboard, name='housekeeping_dashboard'),
    path('dashboard/housekeeping/clean/<int:room_id>/', views.mark_room_clean, name='mark_room_clean'),
    path('dashboard/housekeeping/history/', views.housekeeping_history, name='housekeeping_history'),
    path('dashboard/housekeeping/profile/', views.housekeeping_profile, name='housekeeping_profile'),
    path('django-admin/', admin.site.urls),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
else:
    # Serve uploaded media (hotel/branch logos, room & food images) even in
    # production. Hosts like PythonAnywhere don't serve /media/ by default, which
    # is why uploaded logos/images were not appearing on the dashboard/website.
    from django.urls import re_path
    from django.views.static import serve as _media_serve
    urlpatterns += [
        re_path(r'^media/(?P<path>.*)$', _media_serve, {'document_root': settings.MEDIA_ROOT}),
    ]