import json
import csv
import io
from django.http import HttpResponse, JsonResponse
from django.utils import timezone 
from django.shortcuts import get_object_or_404, render, redirect
from django.contrib.auth import login
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.decorators import login_required
from django.contrib.auth.hashers import make_password 
from accounts.models import (
    Booking, CleaningLog, CustomUser, Customer, Employee, FoodItem, FoodOrder, Room,
    PaymentSetting, PaymentReceipt, Branch, Wallet, WalletTransaction,
    Drink, BarOrder, BarOrderItem, StockTransaction, Message, SiteSetting, Expense,
    Ingredient, IngredientStockTransaction, LaundryService, LaundryOrder, LaundryOrderItem,
    Notification, RoomImage,
    WalletTopUpReceipt, IngredientUsage, SpaService, SpaOrder, SpaOrderItem, AuditLog,
)
from .forms import (
    BookingForm, CustomerEditForm, CustomerSignUpForm, EmployeeCreationForm, EmployeeEditForm,
    FoodItemForm, RoomForm, WalkInBookingForm, PaymentSettingForm, PaymentReceiptForm,
    DrinkForm, RestockForm, BranchForm, MessageForm, SiteSettingForm, ExpenseForm, WalletCreditForm,
    IngredientForm, IngredientRestockForm, LaundryServiceForm, RoomImageForm, SiteContentForm,
    CSVImportForm,
    WalletTopUpForm, WalletTopUpReviewForm, IngredientUsageForm, SpaServiceForm,
)
from . import notifications as notify
from .audit import log_action
from django.db.models import Q
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models.functions import TruncMonth, TruncDay 
from .decorators import admin_required, customer_required, employee_required
from datetime import timedelta, date
from decimal import Decimal, ROUND_HALF_UP
# --- COMMON VIEWS ---


def paginate(request, queryset, per_page=10):
    """Return a Page object for the given queryset (10 items per page by default)."""
    return Paginator(queryset, per_page).get_page(request.GET.get('page'))


# ---------------------------------------------------------------------------
# ROOM AVAILABILITY (date-range based, rooms stay listed even when booked)
# ---------------------------------------------------------------------------
def room_active_bookings(room):
    """Reservations that still block dates: not cancelled, not checked out, ending today or later."""
    today = timezone.now().date()
    return Booking.objects.filter(
        room=room, is_cancelled=False, actual_check_out__isnull=True, check_out__gte=today,
    ).order_by('check_in')


def room_is_available(room, check_in, check_out, exclude_booking_id=None):
    """True if the room is free for the whole [check_in, check_out) range."""
    if room.room_status == 'maintenance':
        return False
    qs = Booking.objects.filter(
        room=room, is_cancelled=False, actual_check_out__isnull=True,
        check_in__lt=check_out, check_out__gt=check_in,
    )
    if exclude_booking_id:
        qs = qs.exclude(id=exclude_booking_id)
    return not qs.exists()


def room_next_available_date(room):
    """Earliest date (>= today) the room is free, skipping past current/overlapping reservations."""
    today = timezone.now().date()
    bookings = list(room_active_bookings(room))
    if not bookings:
        return today
    candidate = today
    changed = True
    while changed:
        changed = False
        for b in bookings:
            if b.check_in <= candidate < b.check_out:
                candidate = b.check_out
                changed = True
    return candidate


def _annotate_room_availability(rooms):
    """Attach booked_ranges + next_available to each room for the listings."""
    rooms = list(rooms)
    for room in rooms:
        room.booked_ranges = list(room_active_bookings(room))
        room.next_available = room_next_available_date(room)
    return rooms


def index(request):
    # Feature a few rooms on the homepage (booked rooms stay listed, only hide maintenance).
    featured_rooms = _annotate_room_availability(Room.objects.exclude(room_status='maintenance')[:3])
    return render(request, 'common/home.html', {
        'featured_rooms': featured_rooms,
        'cms': SiteSetting.load(),
    })

def room_list(request):
    # ---- Optional date-range filter (works for both anonymous and logged in users) --
    qs = Room.objects.exclude(room_status='maintenance').order_by('room_number')

    check_in_str = (request.GET.get('check_in') or '').strip()
    check_out_str = (request.GET.get('check_out') or '').strip()
    q_text = (request.GET.get('q') or '').strip()
    filter_check_in = filter_check_out = None
    try:
        if check_in_str:
            filter_check_in = date.fromisoformat(check_in_str)
        if check_out_str:
            filter_check_out = date.fromisoformat(check_out_str)
    except ValueError:
        filter_check_in = filter_check_out = None

    # Text search across room number / type / description.
    if q_text:
        qs = qs.filter(
            Q(room_number__icontains=q_text) |
            Q(room_type__icontains=q_text) |
            Q(description__icontains=q_text)
        )

    if filter_check_in and filter_check_out and filter_check_in < filter_check_out:
        # Restrict to rooms actually available for the requested dates.
        qs = [r for r in qs if room_is_available(r, filter_check_in, filter_check_out)]

    rooms = _annotate_room_availability(qs)
    ctx = {
        'rooms': rooms,
        'sel_check_in': check_in_str,
        'sel_check_out': check_out_str,
        'sel_q': q_text,
        'filtered': bool(filter_check_in and filter_check_out and filter_check_in < filter_check_out),
    }
    # Logged-in guests keep their dashboard sidebar while browsing rooms.
    if request.user.is_authenticated and request.user.role == 'customer':
        return render(request, 'customer_panel/browse_rooms.html', ctx)
    return render(request, 'common/rooms.html', ctx)

def book_room_placeholder(request, room_id):
    # This is a placeholder until we build the Booking Logic in the next step
    if not request.user.is_authenticated:
        return redirect(f'/login/?next=/book-room/{room_id}/')
    
    room = get_object_or_404(Room, id=room_id)
    return render(request, 'customer_panel/booking_confirm.html', {'room': room})


@login_required
def book_room(request, room_id):
    room = get_object_or_404(Room, id=room_id)

    # Rooms under maintenance can't be booked at all.
    if room.room_status == 'maintenance':
        messages.error(request, "Sorry, this room is currently under maintenance.")
        return redirect('room_list')

    if request.method == 'POST':
        form = BookingForm(request.POST)
        if form.is_valid():
            check_in = form.cleaned_data['check_in']
            check_out = form.cleaned_data['check_out']

            # Date-range availability: the room stays listed, but the chosen
            # dates must not overlap an existing reservation.
            if not room_is_available(room, check_in, check_out):
                next_date = room_next_available_date(room)
                messages.error(
                    request,
                    f"Room {room.room_number} is already reserved for those dates. "
                    f"The next available date is {next_date:%b %d, %Y}. Please choose dates from then on."
                )
            else:
                booking = form.save(commit=False)
                booking.user = request.user
                booking.room = room
                booking.branch = room.branch
                booking.save()
                guest_name = request.user.get_full_name() or request.user.username
                notify.notify_roles(
                    ['admin', 'manager', 'receptionist'], 'new_booking',
                    'New guest booking',
                    f"{guest_name} booked Room {room.room_number} ({booking.check_in:%b %d} – {booking.check_out:%b %d}).",
                    link='/dashboard/admin/bookings/', branch=room.branch,
                )
                messages.success(request, f"Room {room.room_number} reserved! Please complete your payment to confirm the booking.")
                return redirect('pay_booking', booking_id=booking.id)
    else:
        form = BookingForm()

    return render(request, 'customer_panel/booking_form.html', {
        'room': room,
        'form': form,
        'booked_ranges': list(room_active_bookings(room)),
        'next_available': room_next_available_date(room),
    })



def about_us(request):
    return render(request, 'common/about.html', {'cms': SiteSetting.load()})

def register_customer(request):
    if request.method == 'POST':
        form = CustomerSignUpForm(request.POST, request.FILES)
        if form.is_valid():
            user = form.save()
            login(request, user)
            return redirect('customer_dashboard')
    else:
        form = CustomerSignUpForm()
    return render(request, 'common/signup.html', {'form': form})

def login_view(request):
    if request.method == 'POST':
        form = AuthenticationForm(data=request.POST)
        if form.is_valid():
            user = form.get_user()
            login(request, user)
            
            # --- INTELLIGENT REDIRECT LOGIC ---
            # 1. Check if there is a 'next' parameter (e.g., user tried to book a room)
            next_url = request.GET.get('next')
            if next_url:
                return redirect(next_url)
            
            # 2. If no 'next', route based on Role
            if user.role == 'admin':
                return redirect('admin_dashboard')
            elif user.role == 'customer':
                return redirect('customer_dashboard')
            elif user.role == 'employee':
                try:
                    job = user.employee_profile.job_type
                    if job == 'receptionist':
                        return redirect('receptionist_dashboard')
                    elif job == 'kitchen':
                        return redirect('kitchen_dashboard')
                    elif job == 'housekeeping':
                        return redirect('housekeeping_dashboard')
                    elif job == 'bar':
                        return redirect('bar_dashboard')
                    elif job == 'manager':
                        return redirect('manager_dashboard')
                    elif job == 'spa':
                        return redirect('spa_monitor')
                    else:
                        return redirect('home')
                except:
                    return redirect('home')
    else:
        form = AuthenticationForm()
    return render(request, 'common/login.html', {'form': form})

# --- ROLE SPECIFIC DASHBOARDS ---
from django.db.models.functions import TruncMonth
from django.db.models import Count, Sum
@login_required
@admin_required
def admin_dashboard(request):
    # Scope everything to the active branch when one is selected.
    active = _active_branch(request)
    scan_inventory_alerts(active)
    bookings_qs = Booking.objects.all()
    rooms_qs = Room.objects.all()
    if active:
        bookings_qs = bookings_qs.filter(branch=active)
        rooms_qs = rooms_qs.filter(branch=active)

    # ---- Date-range filter (Today / 7 / 30 / 90 days / all) ----
    range_options = [
        ('today', 'Today'),
        ('7', 'Last 7 Days'),
        ('30', 'Last 30 Days'),
        ('90', 'Last 90 Days'),
        ('year', 'This Year'),
        ('all', 'All Time'),
    ]
    valid_ranges = {key for key, _ in range_options}
    selected_range = request.GET.get('range', '7')
    if selected_range not in valid_ranges:
        selected_range = '7'

    now = timezone.now()
    today = now.date()
    start_dt = None
    if selected_range == 'today':
        start_dt = now.replace(hour=0, minute=0, second=0, microsecond=0)
    elif selected_range == '7':
        start_dt = now - timedelta(days=7)
    elif selected_range == '30':
        start_dt = now - timedelta(days=30)
    elif selected_range == '90':
        start_dt = now - timedelta(days=90)
    elif selected_range == 'year':
        start_dt = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
    # 'all' -> start_dt stays None

    period_bookings = bookings_qs
    if start_dt is not None:
        period_bookings = bookings_qs.filter(created_at__gte=start_dt)

    range_label = dict(range_options)[selected_range]

    # 1. KPI CARDS DATA (respect the selected range)
    total_revenue = period_bookings.filter(is_paid=True).aggregate(Sum('total_amount'))['total_amount__sum'] or 0
    total_bookings = period_bookings.count()
    active_guests = bookings_qs.filter(actual_check_in__isnull=False, actual_check_out__isnull=True).count()

    # Calculate Occupancy Rate
    total_rooms = rooms_qs.count()
    occupancy_rate = 0
    if total_rooms > 0:
        occupied_rooms = rooms_qs.filter(room_status='occupied').count()
        occupancy_rate = int((occupied_rooms / total_rooms) * 100)

    # 2. CHART DATA: Revenue Trend over the selected range
    trend_start = start_dt if start_dt is not None else (now - timedelta(days=30))
    daily_data = period_bookings.filter(is_paid=True, created_at__gte=trend_start)\
        .annotate(day=TruncDay('created_at'))\
        .values('day')\
        .annotate(revenue=Sum('total_amount'))\
        .order_by('day')

    chart_months = []
    chart_revenue = []
    for entry in daily_data:
        chart_months.append(entry['day'].strftime('%b %d'))
        chart_revenue.append(float(entry['revenue']))

    # 3. CHART DATA: Room Type Popularity
    room_stats = period_bookings.values('room__room_type')\
        .annotate(count=Count('id'))\
        .order_by('-count')

    room_labels = [(item['room__room_type'] or 'other').replace('_', ' ').title() for item in room_stats]
    room_counts = [item['count'] for item in room_stats]

    context = {
        'total_revenue': total_revenue,
        'total_bookings': total_bookings,
        'active_guests': active_guests,
        'occupancy_rate': occupancy_rate,
        'chart_months': json.dumps(chart_months),
        'chart_revenue': json.dumps(chart_revenue),
        'chart_room_labels': json.dumps(room_labels),
        'chart_room_counts': json.dumps(room_counts),
        'active_branch': active,
        'range_options': range_options,
        'selected_range': selected_range,
        'range_label': range_label,
    }
    return render(request, 'admin_panel/dashboard.html', context)

@login_required
@admin_required
def add_employee(request):
    active = _active_branch(request)
    if request.method == 'POST':
        form = EmployeeCreationForm(request.POST, request.FILES)
        if form.is_valid():
            form.save()
            username = form.cleaned_data.get('username')
            messages.success(request, f'Employee {username} has been added successfully!')
            return redirect('add_employee') # Stay on page to add another
        else:
            messages.error(request, 'Please correct the errors below.')
    else:
        # Default the new staff member to the branch currently being managed.
        form = EmployeeCreationForm(initial={'branch': active} if active else None)
    
    return render(request, 'admin_panel/add_employee.html', {'form': form, 'active_branch': active})


@login_required
@admin_required
def view_employees(request):
    active = _active_branch(request)
    # Fetch all users who have an employee profile
    employees = Employee.objects.select_related('user').all().order_by('-id')
    if active:
        employees = employees.filter(branch=active)
    page_obj = paginate(request, employees)
    return render(request, 'admin_panel/view_employees.html', {'employees': page_obj, 'page_obj': page_obj, 'active_branch': active})

@login_required
@admin_required
def edit_employee(request, employee_id):
    # Get the employee profile and the related user
    employee_profile = get_object_or_404(Employee, id=employee_id)
    user_obj = employee_profile.user
    
    if request.method == 'POST':
        form = EmployeeEditForm(request.POST, request.FILES, instance=user_obj)
        if form.is_valid():
            form.save()
            messages.success(request, f"Details for {user_obj.username} updated successfully!")
            return redirect('view_employees')
    else:
        form = EmployeeEditForm(instance=user_obj)
    
    return render(request, 'admin_panel/edit_employee.html', {'form': form, 'employee': employee_profile})

@login_required
@admin_required
def delete_employee(request, employee_id):
    employee_profile = get_object_or_404(Employee, id=employee_id)
    user_obj = employee_profile.user
    
    # Deleting the user will cascade delete the profile
    username = user_obj.username
    user_obj.delete()
    
    messages.success(request, f"Employee {username} has been deleted.")
    return redirect('view_employees')


@login_required
@admin_required
def view_rooms(request):
    active = _active_branch(request)
    rooms = Room.objects.all().order_by('room_number')
    if active:
        rooms = rooms.filter(branch=active)
    page_obj = paginate(request, rooms)
    return render(request, 'admin_panel/view_rooms.html', {'rooms': page_obj, 'page_obj': page_obj, 'active_branch': active})

@login_required
@admin_required
def add_room(request):
    active = _active_branch(request)
    if request.method == 'POST':
        form = RoomForm(request.POST, request.FILES)
        if form.is_valid():
            room = form.save(commit=False)
            # New rooms belong to the branch currently being managed (or the default).
            if not room.branch_id:
                room.branch = active or _default_branch()
            room.save()
            messages.success(request, "New room added successfully!")
            return redirect('view_rooms')
    else:
        form = RoomForm()
    return render(request, 'admin_panel/add_room.html', {'form': form, 'title': 'Add New Room', 'active_branch': active})

@login_required
@admin_required
def edit_room(request, room_id):
    room = get_object_or_404(Room, id=room_id)
    if request.method == 'POST':
        form = RoomForm(request.POST, request.FILES, instance=room)
        if form.is_valid():
            form.save()
            messages.success(request, f"Room {room.room_number} updated successfully!")
            return redirect('view_rooms')
    else:
        form = RoomForm(instance=room)
    return render(request, 'admin_panel/add_room.html', {'form': form, 'title': 'Edit Room', 'is_edit': True})

@login_required
@admin_required
def delete_room(request, room_id):
    room = get_object_or_404(Room, id=room_id)
    room_number = room.room_number
    room.delete()
    messages.success(request, f"Room {room_number} has been deleted.")
    return redirect('view_rooms')



def _can_manage_wallet(user):
    """Admin and Manager can add credit to guest wallets."""
    if user.role == 'admin':
        return True
    if user.role == 'employee' and hasattr(user, 'employee_profile'):
        return user.employee_profile.job_type == 'manager'
    return False


def _attach_wallet_balances(customers):
    """Attach a `wallet_balance` attribute to each Customer for display."""
    customers = list(customers)
    user_ids = [c.user_id for c in customers]
    balances = {w.user_id: w.balance for w in Wallet.objects.filter(user_id__in=user_ids)}
    for c in customers:
        c.wallet_balance = balances.get(c.user_id, Decimal('0.00'))
    return customers


@login_required
def view_guests(request):
    # Admin, Manager and Receptionist may view guests (and their wallet balance).
    if not (request.user.role == 'admin' or
            (request.user.role == 'employee' and hasattr(request.user, 'employee_profile')
             and request.user.employee_profile.job_type in ('manager', 'receptionist'))):
        return redirect('home')

    guests = Customer.objects.select_related('user').all().order_by('-id')
    page_obj = paginate(request, guests)
    _attach_wallet_balances(page_obj.object_list)
    return render(request, 'admin_panel/view_guests.html', {
        'guests': page_obj,
        'page_obj': page_obj,
        'can_add_credit': _can_manage_wallet(request.user),
        'base_template': _panel_base(request),
    })


@login_required
def add_wallet_credit(request, guest_id):
    """Admin / Manager add reward credit to a guest's wallet."""
    if not _can_manage_wallet(request.user):
        messages.error(request, "Only Admins and Managers can add wallet credit.")
        return redirect('home')

    guest = get_object_or_404(Customer, id=guest_id)
    wallet = _get_wallet(guest.user)

    if request.method == 'POST':
        form = WalletCreditForm(request.POST)
        if form.is_valid():
            amount = form.cleaned_data['amount']
            reason = form.cleaned_data['reason'] or "Loyalty reward credit"
            wallet.credit(amount, reason=reason)
            guest_name = guest.user.get_full_name() or guest.user.username
            messages.success(request, f"Added {_money(amount)} to {guest_name}'s wallet.")
            return redirect('view_guests')
    else:
        form = WalletCreditForm()

    return render(request, 'admin_panel/add_wallet_credit.html', {
        'form': form,
        'guest': guest,
        'wallet': wallet,
        'base_template': _panel_base(request),
    })

@login_required
@admin_required
def edit_guest(request, guest_id):
    guest = get_object_or_404(Customer, id=guest_id)
    user_obj = guest.user
    
    if request.method == 'POST':
        form = CustomerEditForm(request.POST, request.FILES, instance=user_obj)
        if form.is_valid():
            form.save()
            messages.success(request, f"Guest {user_obj.username} updated successfully!")
            return redirect('view_guests')
    else:
        form = CustomerEditForm(instance=user_obj)
    
    return render(request, 'admin_panel/edit_guest.html', {
        'form': form,
        'guest': guest,
        'wallet': _get_wallet(user_obj),
        'credit_form': WalletCreditForm(),
    })

@login_required
@admin_required
def delete_guest(request, guest_id):
    guest = get_object_or_404(Customer, id=guest_id)
    user_obj = guest.user
    username = user_obj.username
    user_obj.delete() # Deletes user + customer profile (cascade)
    messages.success(request, f"Guest {username} has been deleted.")
    return redirect('view_guests')


@login_required
@customer_required
def customer_dashboard(request):
    # 1. Fetch Bookings
    bookings = Booking.objects.filter(user=request.user).order_by('-id')
    recent_bookings = bookings[:5]
    
    # 2. Calculate Analytics
    # Total Spent (Only paid bookings)
    total_spent = bookings.filter(is_paid=True).aggregate(Sum('total_amount'))['total_amount__sum'] or 0
    
    # Total Stays (Completed bookings)
    total_stays = bookings.filter(actual_check_out__isnull=False).count()
    
    # Upcoming Trips
    upcoming_count = bookings.filter(check_in__gte=timezone.now().date(), actual_check_in__isnull=True).count()
    
    # Simple Loyalty Logic
    if total_spent >= 5000:
        loyalty_tier = "Platinum"
        loyalty_color = "text-purple-600"
        loyalty_icon = "crown"
    elif total_spent >= 1000:
        loyalty_tier = "Gold"
        loyalty_color = "text-yellow-600"
        loyalty_icon = "medal"
    else:
        loyalty_tier = "Silver"
        loyalty_color = "text-gray-500"
        loyalty_icon = "shield"

    context = {
        'bookings': recent_bookings,
        'total_spent': total_spent,
        'total_stays': total_stays,
        'upcoming_count': upcoming_count,
        'loyalty_tier': loyalty_tier,
        'loyalty_color': loyalty_color,
        'loyalty_icon': loyalty_icon,
    }
    return render(request, 'customer_panel/dashboard.html', context)


@login_required
@customer_required
def customer_profile(request):
    customer_profile = request.user.customer_profile
    
    if request.method == 'POST':
        form = CustomerEditForm(request.POST, request.FILES, instance=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, "Your profile has been updated successfully!")
            return redirect('customer_profile')
    else:
        form = CustomerEditForm(instance=request.user)
        
    return render(request, 'customer_panel/profile.html', {
        'form': form,
        'customer': customer_profile
    })

@login_required
@customer_required
def customer_bookings(request):
    # Show ALL bookings on this separate page
    all_bookings = Booking.objects.filter(user=request.user).order_by('-id')
    page_obj = paginate(request, all_bookings)
    return render(request, 'customer_panel/my_bookings.html', {'bookings': page_obj, 'page_obj': page_obj})
from datetime import date

@login_required
@employee_required(allowed_jobs=['receptionist'])
def receptionist_dashboard(request):
    today = date.today()
    
    # 1. ARRIVALS (ALL PENDING)
    # Removed check_in__lte=today to show ALL upcoming arrivals if needed, 
    # or keep it if you only want past + today. 
    # Request was "all booking", so we remove the date filter to show anyone who hasn't arrived yet.
    scope = _scope_branch(request)
    arrivals = Booking.objects.filter(
        actual_check_in__isnull=True,
        actual_check_out__isnull=True
    ).order_by('check_in')

    # 2. DEPARTURES (ALL ACTIVE GUESTS)
    # Show everyone currently in-house who needs to leave eventually
    departures = Booking.objects.filter(
        actual_check_in__isnull=False,  # Currently here
        actual_check_out__isnull=True   # Hasn't left
    ).order_by('check_out')

    if scope:
        arrivals = arrivals.filter(branch=scope)
        departures = departures.filter(branch=scope)

    in_house = departures.count()

    return render(request, 'receptionist_panel/dashboard.html', {
        'arrivals': arrivals,
        'departures': departures,
        'in_house_count': in_house,
        'today': today
    })


@login_required
@employee_required(allowed_jobs=['kitchen'])
def kitchen_dashboard(request):
    return render(request, 'kitchen_panel/dashboard.html')

@login_required
@employee_required(allowed_jobs=['housekeeping'])
def housekeeping_dashboard(request):
    return render(request, 'housekeeping_panel/dashboard.html')



@login_required
@employee_required(allowed_jobs=['receptionist', 'manager', 'admin'])
# Note: Admins pass this check if you add 'admin' to role logic or separate decorators
def view_bookings(request):
    # Show active bookings (not yet checked out) first
    scope = _scope_branch(request)
    bookings = Booking.objects.select_related('user', 'room').order_by('-id')
    if scope:
        bookings = bookings.filter(branch=scope)
    page_obj = paginate(request, bookings)
    # RENDER DIFFERENT TEMPLATE BASED ON ROLE
    if request.user.role == 'employee' and hasattr(request.user, 'employee_profile') and request.user.employee_profile.job_type == 'receptionist':
        return render(request, 'receptionist_panel/booking_history.html', {'bookings': page_obj, 'page_obj': page_obj})

    return render(request, 'admin_panel/view_bookings.html', {
        'bookings': page_obj, 'page_obj': page_obj, 'base_template': _panel_base(request),
    })

@login_required
def staff_check_in(request, booking_id):
    if request.user.role not in ['admin', 'employee']:
        return redirect('home')

    booking = get_object_or_404(Booking, id=booking_id)

    if not booking.actual_check_in:
        booking.actual_check_in = timezone.now()
        booking.save()
        # Physically occupy the room now that the guest has arrived.
        room = booking.room
        if room.room_status == 'available':
            room.room_status = 'occupied'
            room.save()
        log_action(request, action='status', module='Booking',
                   summary=f"Checked in guest to Room {room.room_number}",
                   object=booking, branch=booking.branch)
        messages.success(request, f"Guest checked in to Room {booking.room.room_number}")

    # SMART REDIRECT
    if request.user.role == 'receptionist':
        return redirect('receptionist_dashboard')
    return redirect('view_bookings')

@login_required
def staff_check_out(request, booking_id):
    # This is the "Quick Checkout" fallback. 
    # Usually we use the Invoice flow now, but keeping this logic intact.
    if request.user.role not in ['admin', 'employee']:
        return redirect('home')

    booking = get_object_or_404(Booking, id=booking_id)

    if not booking.actual_check_out:
        booking.actual_check_out = timezone.now()
        booking.save()
        room = booking.room
        room.room_status = 'dirty'
        room.save()
        log_action(request, action='status', module='Booking',
                   summary=f"Checked out Room {room.room_number}",
                   object=booking, branch=booking.branch)
        messages.success(request, f"Check-out complete! Room {room.room_number} is marked DIRTY.")

    if request.user.role == 'receptionist':
        return redirect('receptionist_dashboard')
    return redirect('view_bookings')


@login_required
@employee_required(allowed_jobs=['housekeeping'])
def housekeeping_dashboard(request):
    # Tasks
    dirty_rooms = Room.objects.filter(room_status='dirty')
    
    # History (Last 10 cleaned by THIS employee)
    my_history = CleaningLog.objects.filter(employee=request.user.employee_profile).order_by('-cleaned_at')[:10]
    
    return render(request, 'housekeeping_panel/dashboard.html', {
        'dirty_rooms': dirty_rooms,
        'my_history': my_history
    })
@login_required
def mark_room_clean(request, room_id):
    # Security check
    if request.user.role == 'employee' and request.user.employee_profile.job_type != 'housekeeping':
         messages.error(request, "Only Housekeeping staff can perform this action.")
         return redirect('home')
         
    room = get_object_or_404(Room, id=room_id)
    
    if room.room_status == 'dirty':
        # 1. Update Room Status
        room.room_status = 'available'
        room.save()
        
        # 2. Create Cleaning Log
        if hasattr(request.user, 'employee_profile'):
            CleaningLog.objects.create(
                room=room,
                employee=request.user.employee_profile
            )
            
        messages.success(request, f"Room {room.room_number} has been cleaned and logged.")
        
    return redirect('housekeeping_dashboard')


@login_required
@admin_required
def view_cleaning_logs(request):
    logs = CleaningLog.objects.select_related('room', 'employee__user').order_by('-cleaned_at')
    page_obj = paginate(request, logs)
    return render(request, 'admin_panel/view_cleaning_logs.html', {'logs': page_obj, 'page_obj': page_obj})
@login_required
@employee_required(allowed_jobs=['housekeeping'])
def housekeeping_history(request):
    # Fetch ALL history for this employee
    my_history = CleaningLog.objects.filter(employee=request.user.employee_profile).order_by('-cleaned_at')
    page_obj = paginate(request, my_history)
    return render(request, 'housekeeping_panel/history.html', {'logs': page_obj, 'page_obj': page_obj})

@login_required
@employee_required(allowed_jobs=['housekeeping'])
def housekeeping_profile(request):
    if not hasattr(request.user, 'employee_profile'):
        messages.error(request, "Staff profile is only available to staff accounts.")
        return redirect('home')
    employee_profile = request.user.employee_profile
    
    if request.method == 'POST':
        # Reuse the EmployeeEditForm but restrict it if needed
        # Or create a simpler profile form. For now, let's use a simple subset.
        form = EmployeeEditForm(request.POST, request.FILES, instance=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, "Profile updated successfully!")
            return redirect('housekeeping_profile')
    else:
        form = EmployeeEditForm(instance=request.user)
        
    return render(request, 'housekeeping_panel/profile.html', {
        'form': form,
        'employee': employee_profile
    })


@login_required
@customer_required
def order_food(request):
    # 1. Get the guest's ACTIVE booking (Must be Checked In)
    active_booking = Booking.objects.filter(
        user=request.user, 
        actual_check_in__isnull=False, 
        actual_check_out__isnull=True
    ).first()
    
    if not active_booking:
        messages.error(request, "You must be checked into a room to order food.")
        return redirect('customer_dashboard')

    menu_items = _branch_menu_filter(FoodItem.objects.filter(is_available=True), active_booking.branch)
    wallet = _get_wallet(request.user)

    if request.method == 'POST':
        selected_item_ids = request.POST.getlist('items')
        if not selected_item_ids:
            messages.error(request, "Please select at least one item.")
            return redirect('order_food')

        # Create Order
        order = FoodOrder.objects.create(booking=active_booking)
        subtotal = Decimal('0')
        for item_id in selected_item_ids:
            item = FoodItem.objects.get(id=item_id)
            order.items.add(item)
            subtotal += item.price

        vat_rate, vat_amount, total = _apply_vat(subtotal)
        order.total_price = total

        # Optional immediate payment from the credit wallet.
        if request.POST.get('pay_method') == 'wallet':
            if wallet.balance >= total:
                wallet.debit(total, reason=f"Food Order #{order.id}")
                order.is_paid = True
                messages.success(request, f"Order placed and {_money(total)} paid from your wallet!")
            else:
                messages.warning(
                    request,
                    f"Insufficient wallet balance ({_money(wallet.balance)}). The order ({_money(total)}) was added to "
                    f"your room bill — top up your wallet or settle it at checkout / via bank transfer."
                )
        else:
            messages.success(request, "Order placed successfully! It has been added to your room bill.")

        order.save()
        notify.notify_roles(
            ['admin', 'manager', 'kitchen'], 'new_kitchen_order',
            'New kitchen order',
            f"Room {active_booking.room.room_number} placed a food order ({_money(total)}).",
            link='/dashboard/kitchen/', branch=active_booking.branch,
        )
        return redirect('customer_food_history')

    return render(request, 'customer_panel/order_food.html', {
        'menu': menu_items,
        'room': active_booking.room,
        'wallet': wallet,
    })

# --- KITCHEN DASHBOARD ---

@login_required
@employee_required(allowed_jobs=['kitchen', 'manager', 'admin'])
def kitchen_dashboard(request):
    scope = _scope_branch(request)
    scan_inventory_alerts(scope)
    active_orders = FoodOrder.objects.exclude(status='delivered').order_by('created_at')
    if scope:
        active_orders = active_orders.filter(booking__branch=scope)
    return render(request, 'kitchen_panel/dashboard.html', {'orders': active_orders})

@login_required
@employee_required(allowed_jobs=['kitchen', 'manager', 'admin'])
def kitchen_history(request):
    scope = _scope_branch(request)
    # Fetch only DELIVERED orders
    delivered_orders = FoodOrder.objects.filter(status='delivered').order_by('-created_at')
    if scope:
        delivered_orders = delivered_orders.filter(booking__branch=scope)
    page_obj = paginate(request, delivered_orders)
    return render(request, 'kitchen_panel/history.html', {'orders': page_obj, 'page_obj': page_obj})


@login_required
def update_order_status(request, order_id, status):
    order = get_object_or_404(FoodOrder, id=order_id)
    order.status = status

    # LOGIC UPDATE: If marking delivered, save the staff member
    if status == 'delivered':
        if request.user.role == 'employee' and hasattr(request.user, 'employee_profile'):
            order.chef = request.user.employee_profile

    order.save()
    log_action(request, action='status', module='FoodOrder',
               summary=f"Food order #{order.id} -> {order.get_status_display()}",
               object=order, branch=order.booking.branch if order.booking else None)

    # Smart Redirect
    referer = request.META.get('HTTP_REFERER')
    if referer and 'admin' in referer:
         return redirect('admin_kitchen_monitor')
    return redirect('kitchen_dashboard')


from django.db.models import Count
@login_required
@admin_required
def admin_kitchen_history(request):
    scope = _scope_branch(request)
    # 1. Detailed Log: All delivered orders
    delivered_orders = FoodOrder.objects.filter(status='delivered').select_related('booking__room', 'chef__user').order_by('-created_at')
    chef_base = FoodOrder.objects.filter(status='delivered')
    if scope:
        delivered_orders = delivered_orders.filter(booking__branch=scope)
        chef_base = chef_base.filter(booking__branch=scope)

    # 2. Leaderboard: Count orders per staff member
    chef_stats = chef_base\
        .values('chef__user__username', 'chef__user__first_name', 'chef__user__last_name', 'chef__user__profile_picture')\
        .annotate(total_delivered=Count('id'))\
        .order_by('-total_delivered')

    page_obj = paginate(request, delivered_orders)
    return render(request, 'admin_panel/kitchen_history.html', {
        'orders': page_obj,
        'page_obj': page_obj,
        'stats': chef_stats
    })
@login_required
@admin_required
def view_food_menu(request):
    active = _scope_branch(request)
    food_items = FoodItem.objects.all().order_by('category', 'name')
    if active:
        food_items = _branch_menu_filter(food_items, active)
    page_obj = paginate(request, food_items)
    return render(request, 'admin_panel/view_food_menu.html', {'food_items': page_obj, 'page_obj': page_obj, 'active_branch': active})

@login_required
@admin_required
def add_food_item(request):
    active = _active_branch(request)
    if request.method == 'POST':
        form = FoodItemForm(request.POST, request.FILES)
        if form.is_valid():
            item = form.save(commit=False)
            # New menu items default to the branch currently being managed (or the default).
            if not item.branch_id:
                item.branch = active or _default_branch()
            item.save()
            messages.success(request, "New food item added to the menu!")
            return redirect('view_food_menu')
    else:
        form = FoodItemForm(initial={'branch': active} if active else None)
    return render(request, 'admin_panel/add_food_item.html', {'form': form, 'title': 'Add Menu Item', 'active_branch': active})

@login_required
@admin_required
def edit_food_item(request, item_id):
    item = get_object_or_404(FoodItem, id=item_id)
    if request.method == 'POST':
        form = FoodItemForm(request.POST, request.FILES, instance=item)
        if form.is_valid():
            form.save()
            messages.success(request, f"{item.name} updated successfully!")
            return redirect('view_food_menu')
    else:
        form = FoodItemForm(instance=item)
    return render(request, 'admin_panel/add_food_item.html', {'form': form, 'title': 'Edit Menu Item'})

@login_required
@admin_required
def delete_food_item(request, item_id):
    item = get_object_or_404(FoodItem, id=item_id)
    name = item.name
    item.delete()
    messages.success(request, f"{name} has been removed from the menu.")
    return redirect('view_food_menu')

@login_required
@customer_required
def customer_food_history(request):
    # NEW: Show food orders for the current user
    orders = FoodOrder.objects.filter(booking__user=request.user).order_by('-created_at')
    page_obj = paginate(request, orders)
    return render(request, 'customer_panel/food_history.html', {'orders': page_obj, 'page_obj': page_obj})
@login_required
@admin_required
def admin_kitchen_monitor(request):
    # NEW: Admin version of the KDS
    scope = _scope_branch(request)
    active_orders = FoodOrder.objects.exclude(status='delivered').order_by('created_at')
    if scope:
        active_orders = active_orders.filter(booking__branch=scope)
    return render(request, 'admin_panel/kitchen_monitor.html', {'orders': active_orders})


@login_required
@employee_required(allowed_jobs=['kitchen'])
def kitchen_profile(request):
    if not hasattr(request.user, 'employee_profile'):
        messages.error(request, "Staff profile is only available to staff accounts.")
        return redirect('home')
    employee_profile = request.user.employee_profile
    
    if request.method == 'POST':
        form = EmployeeEditForm(request.POST, request.FILES, instance=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, "Chef profile updated successfully!")
            return redirect('kitchen_profile')
    else:
        form = EmployeeEditForm(instance=request.user)
        
    return render(request, 'kitchen_panel/profile.html', {
        'form': form,
        'employee': employee_profile
    })



@login_required
@employee_required(allowed_jobs=['receptionist'])
def receptionist_walkin(request):
    if request.method == 'POST':
        form = WalkInBookingForm(request.POST)
        if form.is_valid():
            # 1. Handle Guest (Find or Create)
            mobile = form.cleaned_data['mobile']
            first_name = form.cleaned_data['first_name']
            last_name = form.cleaned_data['last_name']
            email = form.cleaned_data['email']
            
            # Check if user exists by mobile (assuming username=mobile for walk-ins)
            user, created = CustomUser.objects.get_or_create(
                username=mobile,
                defaults={
                    'first_name': first_name,
                    'last_name': last_name,
                    'email': email,
                    'mobile': mobile,
                    'role': 'customer',
                    'password': make_password(mobile) # Default password is mobile number
                }
            )
            
            if created:
                Customer.objects.create(user=user, address="Walk-in Guest")
                messages.info(request, f"New guest account created for {first_name}.")
            else:
                messages.info(request, f"Found existing guest: {user.get_full_name()}.")

            # 2. Create Booking
            room = form.cleaned_data['room']
            booking = Booking.objects.create(
                user=user,
                room=room,
                branch=room.branch,
                check_in=form.cleaned_data['check_in'],
                check_out=form.cleaned_data['check_out'],
                actual_check_in=timezone.now() # Walk-ins check in immediately
            )
            
            # 3. Update Room Status
            room.room_status = 'occupied'
            room.save()
            
            messages.success(request, f"Walk-in confirmed! Room {room.room_number} is now Occupied.")
            return redirect('receptionist_dashboard')
    else:
        form = WalkInBookingForm()
        
    return render(request, 'receptionist_panel/walkin_booking.html', {'form': form})
from django.db.models import Sum
@login_required
@employee_required(allowed_jobs=['receptionist'])
def receptionist_room_status(request):
    # Show all rooms with visual status
    rooms = Room.objects.all().order_by('room_number')
    return render(request, 'receptionist_panel/room_status.html', {'rooms': rooms})

@login_required
@employee_required(allowed_jobs=['receptionist'])
def receptionist_guest_list(request):
    # List all customers with their wallet balance
    guests = Customer.objects.select_related('user').all().order_by('-id')
    guests = _attach_wallet_balances(guests)
    return render(request, 'receptionist_panel/guest_list.html', {'guests': guests})



@login_required
def generate_invoice(request, booking_id):
    # Allow receptionists AND admins
    if request.user.role not in ['admin', 'employee']:
         return redirect('home')
         
    booking = get_object_or_404(Booking, id=booking_id)
    
    duration = (booking.check_out - booking.check_in).days
    if duration < 1: duration = 1
    
    room_total = duration * booking.room.price_per_night
    food_orders = booking.foodorder_set.all()
    food_total = food_orders.aggregate(Sum('total_price'))['total_price__sum'] or 0
    bar_orders = booking.bar_orders.all()
    bar_total = bar_orders.aggregate(Sum('total_price'))['total_price__sum'] or 0
    subtotal = room_total + food_total + bar_total

    # Apply VAT from site settings
    site = SiteSetting.load()
    vat_rate = site.vat_percentage or 0
    vat_amount = (subtotal * vat_rate) / 100
    grand_total = subtotal + vat_amount

    context = {
        'booking': booking,
        'duration': duration,
        'room_total': room_total,
        'food_orders': food_orders,
        'food_total': food_total,
        'bar_orders': bar_orders,
        'bar_total': bar_total,
        'subtotal': subtotal,
        'vat_rate': vat_rate,
        'vat_amount': vat_amount,
        'grand_total': grand_total,
        'base_template': _panel_base(request),
    }

    # The invoice always reflects the BRANCH the booking belongs to,
    # regardless of who is generating it.
    branch = booking.branch
    if branch:
        context.update({
            'site_hotel_name': branch.name or site.hotel_name,
            'site_hotel_logo': branch.logo.url if branch.logo else (site.hotel_logo.url if site.hotel_logo else ''),
            'site_hotel_address': branch.address or site.hotel_address,
            'site_hotel_phone': branch.phone or site.hotel_phone,
            'site_hotel_email': branch.email or site.hotel_email,
        })

    # CHECK FOR DOWNLOAD MODE
    if request.GET.get('style') == 'clean':
        return render(request, 'receptionist_panel/invoice_clean.html', context)
        
    return render(request, 'receptionist_panel/invoice.html', context)

@login_required
def process_checkout_payment(request, booking_id):
    booking = get_object_or_404(Booking, id=booking_id)
    
    if request.method == 'POST':
        booking.total_amount = request.POST.get('total_amount')
        booking.payment_method = request.POST.get('payment_method')
        booking.is_paid = True
        booking.actual_check_out = timezone.now()
        booking.save()
        
        room = booking.room
        room.room_status = 'dirty'
        room.save()
        
        messages.success(request, f"Payment successful! Guest checked out.")
        
        # SMART REDIRECT
        if request.user.role == 'admin':
            return redirect('view_bookings')
        return redirect('receptionist_dashboard')
        
    return redirect('generate_invoice', booking_id=booking_id)


# ---------------------------------------------------------------------------
# ONLINE PAYMENT (Bank Transfer + Receipt Upload)
# ---------------------------------------------------------------------------

def _calculate_booking_amount(booking):
    """Estimate the amount due for a booking (nights * nightly price)."""
    duration = (booking.check_out - booking.check_in).days
    if duration < 1:
        duration = 1
    return duration * booking.room.price_per_night


@login_required
@admin_required
def payment_settings(request):
    """Admin view to set/change the bank details shown to guests."""
    settings_obj = PaymentSetting.load()

    if request.method == 'POST':
        form = PaymentSettingForm(request.POST, instance=settings_obj)
        if form.is_valid():
            form.save()
            messages.success(request, "Payment / bank details updated successfully!")
            return redirect('payment_settings')
    else:
        form = PaymentSettingForm(instance=settings_obj)

    return render(request, 'admin_panel/payment_settings.html', {'form': form, 'settings': settings_obj})


@login_required
@customer_required
def pay_booking(request, booking_id):
    """Guest pays for a booking via wallet or bank transfer (with receipt upload)."""
    booking = get_object_or_404(Booking, id=booking_id, user=request.user)
    bank = PaymentSetting.load()
    receipts = booking.receipts.all()
    room_subtotal = _money(_calculate_booking_amount(booking))
    vat_rate, vat_amount, amount_due = _apply_vat(room_subtotal)
    wallet = _get_wallet(request.user)

    if request.method == 'POST':
        form = PaymentReceiptForm(request.POST, request.FILES)
        if form.is_valid():
            receipt = form.save(commit=False)
            receipt.booking = booking
            if not receipt.amount:
                receipt.amount = amount_due
            receipt.save()
            messages.success(request, "Receipt uploaded! The receptionist will confirm your payment shortly.")
            return redirect('pay_booking', booking_id=booking.id)
    else:
        form = PaymentReceiptForm(initial={'amount': amount_due})

    return render(request, 'customer_panel/pay_booking.html', {
        'booking': booking,
        'bank': bank,
        'form': form,
        'receipts': receipts,
        'room_subtotal': room_subtotal,
        'vat_rate': vat_rate,
        'vat_amount': vat_amount,
        'amount_due': amount_due,
        'wallet': wallet,
    })


@login_required
@customer_required
def pay_booking_wallet(request, booking_id):
    """Pay for a booking using the guest's credit wallet balance."""
    booking = get_object_or_404(Booking, id=booking_id, user=request.user)
    if booking.is_paid:
        messages.info(request, "This booking is already paid.")
        return redirect('pay_booking', booking_id=booking.id)

    room_subtotal = _money(_calculate_booking_amount(booking))
    _, vat_amount, total_due = _apply_vat(room_subtotal)
    wallet = _get_wallet(request.user)

    if wallet.balance >= total_due:
        wallet.debit(total_due, reason=f"Payment for Booking #{booking.id}")
        booking.is_paid = True
        booking.payment_method = 'Wallet'
        booking.total_amount = total_due
        booking.save()
        messages.success(request, f"Paid {_money(total_due)} from your wallet. Your booking is confirmed!")
    else:
        messages.error(
            request,
            f"Insufficient wallet balance. Your balance is {_money(wallet.balance)} but {_money(total_due)} is required. "
            f"Please complete the payment using the bank transfer option below and upload your receipt."
        )
    return redirect('pay_booking', booking_id=booking.id)


@login_required
@customer_required
def edit_receipt(request, receipt_id):
    """Guest edits a previously uploaded receipt (only while pending)."""
    receipt = get_object_or_404(PaymentReceipt, id=receipt_id, booking__user=request.user)

    if receipt.status == PaymentReceipt.STATUS_CONFIRMED:
        messages.error(request, "This payment is already confirmed and can no longer be edited.")
        return redirect('pay_booking', booking_id=receipt.booking.id)

    if request.method == 'POST':
        form = PaymentReceiptForm(request.POST, request.FILES, instance=receipt)
        if form.is_valid():
            updated = form.save(commit=False)
            # Re-uploading resets the status so the receptionist reviews again.
            updated.status = PaymentReceipt.STATUS_PENDING
            updated.save()
            messages.success(request, "Receipt updated successfully!")
            return redirect('pay_booking', booking_id=receipt.booking.id)
    else:
        form = PaymentReceiptForm(instance=receipt)

    return render(request, 'customer_panel/edit_receipt.html', {
        'form': form,
        'receipt': receipt,
        'booking': receipt.booking,
    })


@login_required
@customer_required
def delete_receipt(request, receipt_id):
    """Guest deletes an uploaded receipt (only while pending/rejected)."""
    receipt = get_object_or_404(PaymentReceipt, id=receipt_id, booking__user=request.user)
    booking_id = receipt.booking.id

    if receipt.status == PaymentReceipt.STATUS_CONFIRMED:
        messages.error(request, "This payment is already confirmed and cannot be deleted.")
        return redirect('pay_booking', booking_id=booking_id)

    receipt.delete()
    messages.success(request, "Receipt deleted successfully.")
    return redirect('pay_booking', booking_id=booking_id)


@login_required
@employee_required(allowed_jobs=['receptionist'])
def pending_payments(request):
    """Receptionist/Admin queue of uploaded receipts awaiting confirmation."""
    receipts = PaymentReceipt.objects.select_related('booking__user', 'booking__room').order_by('-uploaded_at')
    page_obj = paginate(request, receipts)
    return render(request, 'receptionist_panel/pending_payments.html', {'receipts': page_obj, 'page_obj': page_obj})


@login_required
def confirm_payment(request, receipt_id):
    """Receptionist/Admin confirms a receipt and marks the booking paid."""
    if request.user.role not in ['admin', 'employee']:
        return redirect('home')

    receipt = get_object_or_404(PaymentReceipt, id=receipt_id)
    receipt.status = PaymentReceipt.STATUS_CONFIRMED
    receipt.save()

    booking = receipt.booking
    booking.is_paid = True
    booking.payment_method = 'Bank Transfer'
    if not booking.total_amount or booking.total_amount == 0:
        booking.total_amount = receipt.amount or _calculate_booking_amount(booking)
    booking.save()

    log_action(request, action='payment', module='PaymentReceipt',
               summary=f"Confirmed payment for Booking #{booking.id}",
               object=receipt, branch=booking.branch)
    messages.success(request, f"Payment confirmed for Booking #{booking.id}. The reservation is secured.")
    return redirect('pending_payments')


@login_required
def reject_payment(request, receipt_id):
    """Receptionist/Admin rejects a receipt (e.g. wrong amount / invalid proof)."""
    if request.user.role not in ['admin', 'employee']:
        return redirect('home')

    receipt = get_object_or_404(PaymentReceipt, id=receipt_id)
    receipt.status = PaymentReceipt.STATUS_REJECTED
    receipt.save()

    log_action(request, action='payment', module='PaymentReceipt',
               summary=f"Rejected payment for Booking #{receipt.booking.id}",
               object=receipt, branch=receipt.booking.branch if receipt.booking else None)
    messages.error(request, f"Receipt for Booking #{receipt.booking.id} marked as rejected.")
    return redirect('pending_payments')


# ===========================================================================
# HELPERS
# ===========================================================================
def _get_wallet(user):
    wallet, _ = Wallet.objects.get_or_create(user=user)
    return wallet


def _money(value):
    """Quantise any number to 2 decimal places."""
    return Decimal(value or 0).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def _vat_rate():
    try:
        return SiteSetting.load().vat_percentage or Decimal('0')
    except Exception:
        return Decimal('0')


def _apply_vat(subtotal):
    """Return (rate, vat_amount, total_including_vat) for a subtotal."""
    rate = Decimal(_vat_rate())
    subtotal = Decimal(subtotal or 0)
    vat = _money(subtotal * rate / Decimal('100'))
    return rate, vat, _money(subtotal + vat)


def _active_booking_for(user):
    return Booking.objects.filter(
        user=user,
        actual_check_in__isnull=False,
        actual_check_out__isnull=True,
        is_cancelled=False,
    ).first()


def _panel_base(request):
    """Return the correct base template for shared pages, based on the user's role."""
    if request.user.role == 'admin':
        return 'admin_panel/adminbase.html'
    if request.user.role == 'customer':
        return 'customer_panel/customerbase.html'
    if request.user.role == 'employee' and hasattr(request.user, 'employee_profile'):
        job = request.user.employee_profile.job_type
        return {
            'kitchen': 'kitchen_panel/kitchenbase.html',
            'bar': 'bar_panel/barbase.html',
            'manager': 'manager_panel/managerbase.html',
            'receptionist': 'receptionist_panel/receptionistbase.html',
            'housekeeping': 'housekeeping_panel/housekeepingbase.html',
            'spa': 'housekeeping_panel/housekeepingbase.html',
        }.get(job, 'admin_panel/adminbase.html')
    return 'admin_panel/adminbase.html'


def _can_view_audit(user):
    if not user.is_authenticated:
        return False
    if user.role == 'admin':
        return True
    if user.role == 'employee' and hasattr(user, 'employee_profile'):
        return user.employee_profile.job_type == 'manager'
    return False


def _can_review_wallet_topups(user):
    """Admin, Manager and Receptionist can confirm guest wallet top-ups."""
    if not user.is_authenticated:
        return False
    if user.role == 'admin':
        return True
    if user.role == 'employee' and hasattr(user, 'employee_profile'):
        return user.employee_profile.job_type in ('manager', 'receptionist')
    return False


# ===========================================================================
# HOTEL CREDIT WALLET + BOOKING CANCELLATION
# ===========================================================================
@login_required
@customer_required
def customer_wallet(request):
    wallet = _get_wallet(request.user)

    # ---- Date + transaction type filter -----------------------------------
    txn_type = (request.GET.get('type') or 'all').strip().lower()
    start_str = (request.GET.get('start') or '').strip()
    end_str = (request.GET.get('end') or '').strip()

    transactions = wallet.transactions.all()
    if txn_type in ('credit', 'debit'):
        transactions = transactions.filter(txn_type=txn_type)
    start_date = end_date = None
    try:
        if start_str:
            start_date = date.fromisoformat(start_str)
            transactions = transactions.filter(created_at__date__gte=start_date)
    except ValueError:
        start_date = None
    try:
        if end_str:
            end_date = date.fromisoformat(end_str)
            transactions = transactions.filter(created_at__date__lte=end_date)
    except ValueError:
        end_date = None

    # Top-up receipt history for the guest (most recent first)
    topups = WalletTopUpReceipt.objects.filter(user=request.user).order_by('-created_at')[:20]
    pending_topups = WalletTopUpReceipt.objects.filter(user=request.user,
                                                       status=WalletTopUpReceipt.STATUS_PENDING).count()

    return render(request, 'customer_panel/wallet.html', {
        'wallet': wallet,
        'transactions': transactions,
        'topups': topups,
        'pending_topups': pending_topups,
        'sel_type': txn_type if txn_type in ('credit', 'debit') else 'all',
        'sel_start': start_str,
        'sel_end': end_str,
    })


@login_required
@customer_required
def wallet_reload(request):
    """Guest uploads a bank-transfer receipt to top up their wallet."""
    wallet = _get_wallet(request.user)
    if request.method == 'POST':
        form = WalletTopUpForm(request.POST, request.FILES)
        if form.is_valid():
            topup = form.save(commit=False)
            topup.user = request.user
            topup.save()
            guest_name = request.user.get_full_name() or request.user.username
            notify.notify_roles(
                ['admin', 'manager', 'receptionist'], 'wallet_topup',
                'Wallet top-up requested',
                f"{guest_name} uploaded a receipt for {_money(topup.amount)} — please confirm.",
                link='/dashboard/wallet/topups/',
            )
            messages.success(request,
                             "Receipt uploaded. We'll credit your wallet once payment is confirmed.")
            return redirect('customer_wallet')
    else:
        form = WalletTopUpForm()
    return render(request, 'customer_panel/wallet_reload.html', {
        'form': form, 'wallet': wallet,
        'payment_settings': PaymentSetting.load(),
    })


@login_required
def wallet_topup_review(request):
    """Admin / Manager / Receptionist review pending wallet top-up receipts."""
    if not _can_review_wallet_topups(request.user):
        messages.error(request,
                       "Only Admin, Manager and Receptionist can confirm wallet top-ups.")
        return redirect('home')

    status = (request.GET.get('status') or 'pending').lower()
    qs = WalletTopUpReceipt.objects.select_related('user', 'reviewed_by').all()
    if status in (WalletTopUpReceipt.STATUS_PENDING, WalletTopUpReceipt.STATUS_CONFIRMED,
                  WalletTopUpReceipt.STATUS_REJECTED):
        qs = qs.filter(status=status)
    page_obj = paginate(request, qs)
    pending_count = WalletTopUpReceipt.objects.filter(
        status=WalletTopUpReceipt.STATUS_PENDING).count()
    return render(request, 'admin_panel/wallet_topups.html', {
        'topups': page_obj, 'page_obj': page_obj, 'sel_status': status,
        'pending_count': pending_count, 'base_template': _panel_base(request),
    })


@login_required
def wallet_topup_decide(request, topup_id):
    if not _can_review_wallet_topups(request.user):
        messages.error(request, "Permission denied.")
        return redirect('home')
    topup = get_object_or_404(WalletTopUpReceipt, id=topup_id)
    if topup.status != WalletTopUpReceipt.STATUS_PENDING:
        messages.info(request, "This top-up has already been reviewed.")
        return redirect('wallet_topup_review')

    if request.method == 'POST':
        form = WalletTopUpReviewForm(request.POST)
        if form.is_valid():
            decision = form.cleaned_data['decision']
            note = form.cleaned_data.get('review_note', '')
            topup.review_note = note
            topup.reviewed_by = request.user
            topup.reviewed_at = timezone.now()
            if decision == 'confirm':
                wallet = _get_wallet(topup.user)
                wallet.credit(topup.amount, reason=f"Wallet top-up #{topup.id} confirmed")
                topup.status = WalletTopUpReceipt.STATUS_CONFIRMED
                topup.save()
                log_action(request, action='payment', module='WalletTopUp',
                           summary=f"Confirmed wallet top-up of {_money(topup.amount)} for {topup.user.username}",
                           object=topup)
                notify.notify_user(topup.user, 'wallet_topup',
                                   'Wallet top-up confirmed',
                                   f"{_money(topup.amount)} has been credited to your wallet.",
                                   link='/dashboard/customer/wallet/')
                messages.success(request,
                                 f"Top-up confirmed and {_money(topup.amount)} credited to {topup.user.username}.")
            else:
                topup.status = WalletTopUpReceipt.STATUS_REJECTED
                topup.save()
                log_action(request, action='payment', module='WalletTopUp',
                           summary=f"Rejected wallet top-up of {_money(topup.amount)} for {topup.user.username}",
                           object=topup)
                notify.notify_user(topup.user, 'wallet_topup',
                                   'Wallet top-up rejected',
                                   note or 'Please contact reception for assistance.',
                                   link='/dashboard/customer/wallet/')
                messages.success(request, "Top-up marked as rejected.")
            return redirect('wallet_topup_review')
    else:
        form = WalletTopUpReviewForm()
    return render(request, 'admin_panel/wallet_topup_review.html', {
        'topup': topup, 'form': form, 'base_template': _panel_base(request),
    })


@login_required
@customer_required
def cancel_booking(request, booking_id):
    booking = get_object_or_404(Booking, id=booking_id, user=request.user)

    if booking.is_cancelled:
        messages.error(request, "This booking is already cancelled.")
        return redirect('customer_bookings')

    if booking.actual_check_in:
        messages.error(request, "You cannot cancel after you have checked in.")
        return redirect('customer_bookings')

    # Determine refund amount
    refund = booking.total_amount or 0
    if not refund:
        confirmed = booking.receipts.filter(status=PaymentReceipt.STATUS_CONFIRMED).aggregate(Sum('amount'))['amount__sum']
        refund = confirmed or 0

    if booking.is_paid and refund > 0:
        wallet = _get_wallet(request.user)
        wallet.credit(refund, reason=f"Refund for cancelled Booking #{booking.id}")
        messages.success(request, f"Booking cancelled. {refund} has been refunded to your hotel credit wallet.")
    else:
        messages.success(request, "Booking cancelled successfully.")

    # Free the room
    room = booking.room
    if room.room_status in ['occupied', 'reserved']:
        room.room_status = 'available'
        room.save()

    booking.is_cancelled = True
    booking.cancelled_at = timezone.now()
    booking.save()

    guest_name = request.user.get_full_name() or request.user.username
    notify.notify_roles(
        ['admin', 'manager', 'receptionist'], 'cancel_booking',
        'Booking cancelled',
        f"{guest_name} cancelled their booking for Room {room.room_number}.",
        link='/dashboard/admin/bookings/', branch=booking.branch,
    )
    return redirect('customer_bookings')


# ===========================================================================
# ADMIN: SITE SETTINGS (Currency + VAT)
# ===========================================================================
@login_required
@admin_required
def site_settings(request):
    settings_obj = SiteSetting.load()
    if request.method == 'POST':
        # IMPORTANT: pass request.FILES so the uploaded hotel logo is actually saved.
        form = SiteSettingForm(request.POST, request.FILES, instance=settings_obj)
        if form.is_valid():
            form.save()
            messages.success(request, "Site settings (currency / VAT / hotel logo) updated successfully!")
            return redirect('site_settings')
    else:
        form = SiteSettingForm(instance=settings_obj)
    return render(request, 'admin_panel/site_settings.html', {'form': form, 'settings': settings_obj})


# ===========================================================================
# BAR SECTION - CUSTOMER ORDERING
# ===========================================================================
@login_required
@customer_required
def order_drinks(request):
    active_booking = _active_booking_for(request.user)
    if not active_booking:
        messages.error(request, "You must be checked into a room to order from the bar.")
        return redirect('customer_dashboard')

    drinks = _branch_menu_filter(Drink.objects.filter(is_available=True, stock_quantity__gt=0), active_booking.branch)
    wallet = _get_wallet(request.user)

    if request.method == 'POST':
        order = BarOrder.objects.create(booking=active_booking)
        subtotal = Decimal('0')
        any_item = False
        for drink in drinks:
            qty = int(request.POST.get(f'qty_{drink.id}', 0) or 0)
            if qty > 0:
                qty = min(qty, drink.stock_quantity)  # never oversell
                BarOrderItem.objects.create(order=order, drink=drink, quantity=qty, price=drink.price)
                drink.stock_quantity -= qty
                drink.save()
                StockTransaction.objects.create(drink=drink, quantity=-qty, note=f"Bar Order #{order.id}")
                subtotal += qty * drink.price
                any_item = True

        if not any_item:
            order.delete()
            messages.error(request, "Please select at least one drink.")
            return redirect('order_drinks')

        vat_rate, vat_amount, total = _apply_vat(subtotal)
        order.total_price = total

        if request.POST.get('pay_method') == 'wallet':
            if wallet.balance >= total:
                wallet.debit(total, reason=f"Bar Order #{order.id}")
                order.is_paid = True
                messages.success(request, f"Drink order placed and {_money(total)} paid from your wallet!")
            else:
                messages.warning(
                    request,
                    f"Insufficient wallet balance ({_money(wallet.balance)}). The order ({_money(total)}) was added to "
                    f"your room bill — top up your wallet or settle it at checkout / via bank transfer."
                )
        else:
            messages.success(request, "Drink order placed! It has been added to your room bill.")

        order.save()
        notify.notify_roles(
            ['admin', 'manager', 'bar'], 'new_bar_order',
            'New bar order',
            f"Room {active_booking.room.room_number} placed a bar order ({_money(total)}).",
            link='/dashboard/bar/', branch=active_booking.branch,
        )
        # Low-stock alerts triggered by this sale.
        for it in order.items.select_related('drink'):
            d = it.drink
            if d and d.is_low_stock:
                notify.notify_roles(
                    ['admin', 'manager', 'bar'], 'low_stock',
                    f"Low stock: {d.name}",
                    f"Only {d.stock_quantity} left — due for restock.",
                    link='/dashboard/bar/inventory/', branch=d.branch,
                )
        return redirect('customer_bar_history')

    return render(request, 'customer_panel/order_drinks.html', {'drinks': drinks, 'room': active_booking.room, 'wallet': wallet})


@login_required
@customer_required
def customer_bar_history(request):
    orders = BarOrder.objects.filter(booking__user=request.user).prefetch_related('items__drink').order_by('-created_at')
    page_obj = paginate(request, orders)
    return render(request, 'customer_panel/bar_history.html', {'orders': page_obj, 'page_obj': page_obj})


# ===========================================================================
# BAR SECTION - STAFF (Orders + Inventory)
# ===========================================================================
@login_required
@employee_required(allowed_jobs=['bar'])
def bar_dashboard(request):
    scope = _scope_branch(request)
    scan_inventory_alerts(scope)
    active_orders = BarOrder.objects.exclude(status='served').prefetch_related('items__drink')
    low_stock = Drink.objects.filter(stock_quantity__lte=5).order_by('stock_quantity')
    if scope:
        active_orders = active_orders.filter(booking__branch=scope)
        low_stock = _branch_menu_filter(low_stock, scope)
    low_stock = low_stock[:5]
    return render(request, 'bar_panel/dashboard.html', {'orders': active_orders, 'low_stock': low_stock})


@login_required
@employee_required(allowed_jobs=['bar'])
def update_bar_order_status(request, order_id, status):
    order = get_object_or_404(BarOrder, id=order_id)
    order.status = status
    if status == 'served' and request.user.role == 'employee' and hasattr(request.user, 'employee_profile'):
        order.bar_staff = request.user.employee_profile
    order.save()
    log_action(request, action='status', module='BarOrder',
               summary=f"Bar order #{order.id} -> {order.get_status_display()}",
               object=order, branch=order.booking.branch if order.booking else None)
    return redirect('bar_dashboard')


@login_required
@employee_required(allowed_jobs=['bar'])
def bar_history(request):
    scope = _scope_branch(request)
    orders = BarOrder.objects.filter(status='served').prefetch_related('items__drink').order_by('-created_at')
    if scope:
        orders = orders.filter(booking__branch=scope)
    page_obj = paginate(request, orders)
    return render(request, 'bar_panel/history.html', {'orders': page_obj, 'page_obj': page_obj})


@login_required
@employee_required(allowed_jobs=['bar', 'manager'])
def bar_inventory(request):
    active = _scope_branch(request)
    # Trigger expiry / low-stock alerts so the bell badge updates the moment a
    # bar/admin opens the inventory page.
    scan_inventory_alerts(active)
    drinks = Drink.objects.all().order_by('name')
    if active:
        drinks = _branch_menu_filter(drinks, active)
    page_obj = paginate(request, drinks)
    return render(request, 'bar_panel/inventory.html', {'drinks': page_obj, 'page_obj': page_obj, 'active_branch': active, 'base_template': _panel_base(request)})


@login_required
@employee_required(allowed_jobs=['bar', 'manager'])
def add_drink(request):
    active = _active_branch(request)
    if request.method == 'POST':
        form = DrinkForm(request.POST, request.FILES)
        if form.is_valid():
            drink = form.save(commit=False)
            if not drink.branch_id:
                drink.branch = active or _default_branch()
            drink.save()
            log_action(request, action='create', module='Drink',
                       summary=f"Added drink {drink.name}", object=drink, branch=drink.branch)
            messages.success(request, "New drink added to the bar menu!")
            return redirect('bar_inventory')
    else:
        form = DrinkForm(initial={'branch': active} if active else None)
    return render(request, 'bar_panel/drink_form.html', {'form': form, 'title': 'Add Drink', 'active_branch': active, 'base_template': _panel_base(request)})


@login_required
@employee_required(allowed_jobs=['bar', 'manager'])
def edit_drink(request, drink_id):
    drink = get_object_or_404(Drink, id=drink_id)
    if request.method == 'POST':
        form = DrinkForm(request.POST, request.FILES, instance=drink)
        if form.is_valid():
            form.save()
            log_action(request, action='update', module='Drink',
                       summary=f"Updated drink {drink.name}", object=drink, branch=drink.branch)
            messages.success(request, f"{drink.name} updated successfully!")
            return redirect('bar_inventory')
    else:
        form = DrinkForm(instance=drink)
    return render(request, 'bar_panel/drink_form.html', {'form': form, 'title': 'Edit Drink', 'base_template': _panel_base(request)})


@login_required
@employee_required(allowed_jobs=['bar', 'manager'])
def delete_drink(request, drink_id):
    drink = get_object_or_404(Drink, id=drink_id)
    name = drink.name
    branch = drink.branch
    log_action(request, action='delete', module='Drink',
               summary=f"Deleted drink {name}", object=drink, branch=branch)
    drink.delete()
    messages.success(request, f"{name} removed from the bar menu.")
    return redirect('bar_inventory')


@login_required
@employee_required(allowed_jobs=['bar', 'manager'])
def restock_drink(request, drink_id):
    drink = get_object_or_404(Drink, id=drink_id)
    if request.method == 'POST':
        form = RestockForm(request.POST)
        if form.is_valid():
            qty = form.cleaned_data['quantity']
            note = form.cleaned_data['note'] or "Manual restock"
            drink.stock_quantity += qty
            drink.save()
            StockTransaction.objects.create(drink=drink, quantity=qty, note=note)
            log_action(request, action='update', module='Drink',
                       summary=f"Restocked {drink.name} by {qty}", object=drink, branch=drink.branch)
            messages.success(request, f"Restocked {qty} units of {drink.name}.")
            return redirect('bar_inventory')
    else:
        form = RestockForm()
    return render(request, 'bar_panel/restock.html', {'form': form, 'drink': drink, 'base_template': _panel_base(request)})


@login_required
@employee_required(allowed_jobs=['bar'])
def bar_profile(request):
    # Profile pages are only meaningful for the actual staff member.
    if not hasattr(request.user, 'employee_profile'):
        messages.error(request, "Staff profile is only available to staff accounts.")
        return redirect('home')
    employee_profile = request.user.employee_profile
    if request.method == 'POST':
        form = EmployeeEditForm(request.POST, request.FILES, instance=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, "Profile updated successfully!")
            return redirect('bar_profile')
    else:
        form = EmployeeEditForm(instance=request.user)
    return render(request, 'bar_panel/profile.html', {'form': form, 'employee': employee_profile})


# ===========================================================================
# SALES RECORD (Food + Bar) - mark as paid
# ===========================================================================
@login_required
@employee_required(allowed_jobs=['kitchen', 'bar', 'manager'])
def sales_record(request):
    scope = _scope_branch(request)
    food_orders = FoodOrder.objects.select_related('booking__room', 'booking__user').order_by('-created_at')
    bar_orders = BarOrder.objects.select_related('booking__room', 'booking__user').prefetch_related('items__drink').order_by('-created_at')
    if scope:
        food_orders = food_orders.filter(booking__branch=scope)
        bar_orders = bar_orders.filter(booking__branch=scope)

    food_total = food_orders.filter(is_paid=True).aggregate(Sum('total_price'))['total_price__sum'] or 0
    bar_total = bar_orders.filter(is_paid=True).aggregate(Sum('total_price'))['total_price__sum'] or 0
    pending_count = food_orders.filter(is_paid=False).count() + bar_orders.filter(is_paid=False).count()

    return render(request, 'kitchen_panel/sales_record.html', {
        'food_orders': food_orders,
        'bar_orders': bar_orders,
        'food_total': food_total,
        'bar_total': bar_total,
        'grand_total': food_total + bar_total,
        'pending_count': pending_count,
        'base_template': _panel_base(request),
    })


@login_required
@employee_required(allowed_jobs=['kitchen', 'bar', 'manager'])
def mark_food_paid(request, order_id):
    order = get_object_or_404(FoodOrder, id=order_id)
    order.is_paid = True
    order.save()
    messages.success(request, f"Food Order #{order.id} marked as paid.")
    return redirect('sales_record')


@login_required
@employee_required(allowed_jobs=['kitchen', 'bar', 'manager'])
def mark_bar_paid(request, order_id):
    order = get_object_or_404(BarOrder, id=order_id)
    order.is_paid = True
    order.save()
    messages.success(request, f"Bar Order #{order.id} marked as paid.")
    return redirect('sales_record')


# ===========================================================================
# IN-APP MESSAGING
# ===========================================================================
def _current_department(user):
    """Return the department code for a user (used to hide their own dept in compose)."""
    if user.role == 'admin':
        return 'admin'
    if user.role == 'employee' and hasattr(user, 'employee_profile'):
        return user.employee_profile.job_type
    return None


def _department_recipients(department):
    """All active users belonging to a department/role."""
    if department == 'admin':
        return CustomUser.objects.filter(role='admin', is_active=True)
    if department == 'guest':
        return CustomUser.objects.filter(role='customer', is_active=True)
    return CustomUser.objects.filter(
        role='employee', is_active=True, employee_profile__job_type=department
    )


def _can_message_anyone(user):
    """Admin, Manager and Receptionist can target individuals/everyone/guests."""
    if user.role == 'admin':
        return True
    if user.role == 'employee' and hasattr(user, 'employee_profile'):
        return user.employee_profile.job_type in ('manager', 'receptionist')
    return False


@login_required
def inbox(request):
    received = Message.objects.filter(recipient=request.user).select_related('sender')
    page_obj = paginate(request, received)
    return render(request, 'messaging/inbox.html', {
        'messages_list': page_obj,
        'page_obj': page_obj,
        'base_template': _panel_base(request),
        'active_tab': 'inbox',
    })


@login_required
def sent_messages(request):
    sent = Message.objects.filter(sender=request.user).select_related('recipient')
    page_obj = paginate(request, sent)
    return render(request, 'messaging/sent.html', {
        'messages_list': page_obj,
        'page_obj': page_obj,
        'base_template': _panel_base(request),
        'active_tab': 'sent',
    })


@login_required
def compose_message(request):
    my_dept = _current_department(request.user)
    privileged = _can_message_anyone(request.user)

    if request.method == 'POST':
        form = MessageForm(request.POST, user=request.user, privileged=privileged, exclude_department=my_dept)
        if form.is_valid():
            target = form.cleaned_data.get('target_type') or MessageForm.TARGET_DEPARTMENT
            subject = form.cleaned_data['subject']
            body = form.cleaned_data['body']

            recipient_role = ''
            target_label = ''

            if privileged and target == MessageForm.TARGET_INDIVIDUAL:
                person = form.cleaned_data['recipient']
                recipients = [person] if person else []
                target_label = person.get_full_name() or person.username if person else ''
            elif privileged and target == MessageForm.TARGET_EVERYONE:
                recipients = list(CustomUser.objects.filter(is_active=True).exclude(id=request.user.id))
                target_label = "everyone (all guests & staff)"
            else:
                department = form.cleaned_data['department']
                recipients = list(_department_recipients(department).exclude(id=request.user.id))
                recipient_role = department
                target_label = dict(Message.DEPARTMENT_CHOICES).get(department, department)

            sender_name = request.user.get_full_name() or request.user.username
            count = 0
            for user in recipients:
                Message.objects.create(
                    sender=request.user,
                    recipient=user,
                    recipient_role=recipient_role,
                    subject=subject,
                    body=body,
                )
                notify.notify_user(
                    user, 'new_message',
                    f"New message from {sender_name}",
                    subject or body[:60],
                    link='/messages/inbox/',
                )
                count += 1

            if count:
                messages.success(request, f"Message sent to {count} recipient(s) — {target_label}.")
            else:
                messages.warning(request, "No active recipients found, message not delivered.")
            return redirect('sent_messages')
    else:
        form = MessageForm(user=request.user, privileged=privileged, exclude_department=my_dept)
    return render(request, 'messaging/compose.html', {
        'form': form,
        'privileged': privileged,
        'base_template': _panel_base(request),
        'active_tab': 'compose',
    })


@login_required
def reply_message(request, message_id):
    """Reply directly to the person who sent you a message."""
    original = get_object_or_404(Message, id=message_id)
    if request.user not in [original.sender, original.recipient]:
        return redirect('inbox')

    target = original.sender if original.sender != request.user else original.recipient
    body = (request.POST.get('body') or '').strip()
    if request.method == 'POST' and body:
        subject = original.subject if original.subject.lower().startswith('re:') else f"Re: {original.subject}".strip()
        Message.objects.create(
            sender=request.user,
            recipient=target,
            recipient_role='',
            subject=subject,
            body=body,
        )
        notify.notify_user(
            target, 'new_message',
            f"New message from {request.user.get_full_name() or request.user.username}",
            subject, link='/messages/inbox/',
        )
        messages.success(request, f"Reply sent to {target.get_full_name() or target.username}.")
    else:
        messages.error(request, "Reply cannot be empty.")
    return redirect('view_message', message_id=original.id)


@login_required
def view_message(request, message_id):
    msg = get_object_or_404(Message, id=message_id)
    if request.user not in [msg.sender, msg.recipient]:
        return redirect('inbox')
    if msg.recipient == request.user and not msg.is_read:
        msg.is_read = True
        msg.save()
    return render(request, 'messaging/view_message.html', {
        'msg': msg,
        'base_template': _panel_base(request),
    })


@login_required
def delete_message(request, message_id):
    msg = get_object_or_404(Message, id=message_id)
    if request.user in [msg.sender, msg.recipient]:
        msg.delete()
        messages.success(request, "Message deleted.")
    return redirect('inbox')


# ===========================================================================
# MULTI-BRANCH MANAGEMENT (Admin + Manager)
# ===========================================================================
@login_required
@employee_required(allowed_jobs=['manager'])
def manage_branches(request):
    branches = Branch.objects.all()
    page_obj = paginate(request, branches)
    active = _active_branch(request)
    # The first branch acts as the default to switch back to.
    default_branch = Branch.objects.order_by('id').first()
    return render(request, 'admin_panel/branches.html', {
        'branches': page_obj,
        'page_obj': page_obj,
        'active_branch': active,
        'default_branch': default_branch,
        'base_template': _panel_base(request),
    })


@login_required
@employee_required(allowed_jobs=['manager'])
def add_branch(request):
    if request.method == 'POST':
        form = BranchForm(request.POST, request.FILES)
        if form.is_valid():
            form.save()
            messages.success(request, "Branch created successfully!")
            return redirect('manage_branches')
    else:
        form = BranchForm()
    return render(request, 'admin_panel/branch_form.html', {'form': form, 'title': 'Add Branch', 'base_template': _panel_base(request)})


@login_required
@employee_required(allowed_jobs=['manager'])
def edit_branch(request, branch_id):
    branch = get_object_or_404(Branch, id=branch_id)
    if request.method == 'POST':
        form = BranchForm(request.POST, request.FILES, instance=branch)
        if form.is_valid():
            form.save()
            messages.success(request, f"Branch {branch.name} updated.")
            return redirect('manage_branches')
    else:
        form = BranchForm(instance=branch)
    return render(request, 'admin_panel/branch_form.html', {'form': form, 'title': 'Edit Branch', 'base_template': _panel_base(request)})


@login_required
@employee_required(allowed_jobs=['manager'])
def delete_branch(request, branch_id):
    branch = get_object_or_404(Branch, id=branch_id)
    name = branch.name
    branch.delete()
    messages.success(request, f"Branch {name} deleted.")
    return redirect('manage_branches')


@login_required
def switch_branch(request, branch_id):
    # Only admin/manager can switch the active branch context.
    is_manager = request.user.role == 'admin' or (
        request.user.role == 'employee' and hasattr(request.user, 'employee_profile')
        and request.user.employee_profile.job_type == 'manager'
    )
    if not is_manager:
        return redirect('home')

    if branch_id == 0:
        request.session.pop('active_branch_id', None)
        messages.info(request, "Now viewing ALL branches.")
    else:
        branch = get_object_or_404(Branch, id=branch_id)
        request.session['active_branch_id'] = branch.id
        messages.success(request, f"Switched to {branch.name}. Dashboard, rooms, staff, menu, orders, reports and the hotel name/logo now reflect this branch.")

    # Send the user to their dashboard so the branch change is immediately visible.
    if request.user.role == 'admin':
        return redirect('admin_dashboard')
    return redirect('manager_dashboard')


def _active_branch(request):
    """Return the Branch the admin/manager is currently scoped to (or None = all)."""
    bid = request.session.get('active_branch_id')
    if bid:
        return Branch.objects.filter(id=bid).first()
    return None


def _default_branch():
    """The hotel's primary branch — first active one, else the first created."""
    return (Branch.objects.filter(is_active=True).order_by('id').first()
            or Branch.objects.order_by('id').first())


def _scope_branch(request):
    """
    Branch whose OPERATIONAL data the current user should see (None = all branches):
      - admin / manager -> the branch they switched to (session); None = all
      - other staff     -> their own assigned branch (None => all, for legacy/unassigned)
    """
    user = request.user
    if not user.is_authenticated:
        return None
    if user.role == 'admin':
        return _active_branch(request)
    if user.role == 'employee' and hasattr(user, 'employee_profile'):
        emp = user.employee_profile
        if emp.job_type == 'manager':
            return _active_branch(request)
        return emp.branch
    return None


def _branch_menu_filter(queryset, branch):
    """Items for the given branch PLUS legacy items with no branch assigned."""
    if branch is None:
        return queryset
    return queryset.filter(Q(branch=branch) | Q(branch__isnull=True))


@login_required
@employee_required(allowed_jobs=['manager'])
def manager_dashboard(request):
    active_branch_id = request.session.get('active_branch_id')

    bookings = Booking.objects.filter(is_cancelled=False)
    rooms = Room.objects.all()
    staff = Employee.objects.all()

    if active_branch_id:
        bookings = bookings.filter(branch_id=active_branch_id)
        rooms = rooms.filter(branch_id=active_branch_id)
        staff = staff.filter(branch_id=active_branch_id)

    total_revenue = bookings.filter(is_paid=True).aggregate(Sum('total_amount'))['total_amount__sum'] or 0
    total_bookings = bookings.count()
    total_rooms = rooms.count()
    occupied = rooms.filter(room_status='occupied').count()
    occupancy = int((occupied / total_rooms) * 100) if total_rooms else 0

    context = {
        'total_revenue': total_revenue,
        'total_bookings': total_bookings,
        'total_rooms': total_rooms,
        'occupancy_rate': occupancy,
        'staff_count': staff.count(),
        'recent_bookings': bookings.select_related('user', 'room').order_by('-id')[:8],
        'branches': Branch.objects.filter(is_active=True),
        'active_branch': _active_branch(request),
    }
    return render(request, 'manager_panel/dashboard.html', context)


# ===========================================================================
# EXPENSES (Admin + Manager)
# ===========================================================================
@login_required
def expense_list(request):
    if not _can_manage_wallet(request.user):
        messages.error(request, "Only Admins and Managers can access expenses.")
        return redirect('home')

    active = _active_branch(request)
    expenses = Expense.objects.select_related('branch', 'recorded_by').all()
    if active:
        expenses = expenses.filter(branch=active)

    total_expenses = expenses.aggregate(Sum('amount'))['amount__sum'] or 0
    page_obj = paginate(request, expenses)
    return render(request, 'admin_panel/expenses.html', {
        'expenses': page_obj,
        'page_obj': page_obj,
        'total_expenses': total_expenses,
        'active_branch': active,
        'base_template': _panel_base(request),
    })


@login_required
def add_expense(request):
    if not _can_manage_wallet(request.user):
        return redirect('home')
    active = _active_branch(request)
    if request.method == 'POST':
        form = ExpenseForm(request.POST)
        if form.is_valid():
            expense = form.save(commit=False)
            expense.recorded_by = request.user
            if active and not expense.branch_id:
                expense.branch = active
            expense.save()
            messages.success(request, f"Expense '{expense.title}' recorded.")
            return redirect('expense_list')
    else:
        form = ExpenseForm(initial={'spent_on': timezone.now().date(), 'branch': active})
    return render(request, 'admin_panel/expense_form.html', {
        'form': form, 'title': 'Record Expense', 'base_template': _panel_base(request),
    })


@login_required
def edit_expense(request, expense_id):
    if not _can_manage_wallet(request.user):
        return redirect('home')
    expense = get_object_or_404(Expense, id=expense_id)
    if request.method == 'POST':
        form = ExpenseForm(request.POST, instance=expense)
        if form.is_valid():
            form.save()
            messages.success(request, "Expense updated.")
            return redirect('expense_list')
    else:
        form = ExpenseForm(instance=expense)
    return render(request, 'admin_panel/expense_form.html', {
        'form': form, 'title': 'Edit Expense', 'base_template': _panel_base(request),
    })


@login_required
def delete_expense(request, expense_id):
    if not _can_manage_wallet(request.user):
        return redirect('home')
    expense = get_object_or_404(Expense, id=expense_id)
    expense.delete()
    messages.success(request, "Expense deleted.")
    return redirect('expense_list')


# ===========================================================================
# ACCOUNTING & REPORT (Admin + Manager)
# ===========================================================================
import calendar as _calendar


def _period_range(period):
    """Return (start_date, end_date, label) for day/week/month/year (relative to today)."""
    today = timezone.now().date()
    if period == 'day':
        return today, today, "Today"
    if period == 'week':
        return today - timedelta(days=6), today, "This Week (last 7 days)"
    if period == 'year':
        return date(today.year, 1, 1), today, f"This Year ({today.year})"
    # default: month (current calendar month)
    return today.replace(day=1), today, today.strftime("This Month (%B %Y)")


def _resolve_report_range(request):
    """
    Work out the (start, end, label) for the accounting report.

    Supports both the quick relative buttons (period=day/week/month/year) and
    explicit historical selection via ?year=YYYY, ?month=1-12 and ?day=YYYY-MM-DD,
    so admins/managers can view any previous or current year / month / day.
    """
    today = timezone.now().date()

    # 1. Specific day chosen via date picker.
    day_str = (request.GET.get('day') or '').strip()
    if day_str:
        try:
            d = date.fromisoformat(day_str)
            return d, d, d.strftime("%d %b %Y")
        except ValueError:
            pass

    year_str = (request.GET.get('year') or '').strip()
    month_str = (request.GET.get('month') or '').strip()

    # 2. Explicit year (and optionally month).
    if year_str:
        try:
            year = int(year_str)
        except ValueError:
            year = today.year
        if month_str:
            try:
                month = int(month_str)
            except ValueError:
                month = 0
            if 1 <= month <= 12:
                last_day = _calendar.monthrange(year, month)[1]
                start = date(year, month, 1)
                end = date(year, month, last_day)
                return start, end, start.strftime("%B %Y")
        # Whole year
        return date(year, 1, 1), date(year, 12, 31), f"Year {year}"

    # 3. Fall back to the relative quick buttons.
    period = request.GET.get('period', 'month')
    if period not in ('day', 'week', 'month', 'year'):
        period = 'month'
    return _period_range(period)


@login_required
def accounting_report(request):
    if not _can_manage_wallet(request.user):
        messages.error(request, "Only Admins and Managers can view the accounting report.")
        return redirect('home')

    period = request.GET.get('period', 'month')
    if period not in ('day', 'week', 'month', 'year'):
        period = 'month'
    start, end, label = _resolve_report_range(request)

    active = _active_branch(request)

    bookings = Booking.objects.filter(is_paid=True, created_at__date__gte=start, created_at__date__lte=end)
    food = FoodOrder.objects.filter(is_paid=True, created_at__date__gte=start, created_at__date__lte=end)
    bar = BarOrder.objects.filter(is_paid=True, created_at__date__gte=start, created_at__date__lte=end)
    laundry = LaundryOrder.objects.filter(is_paid=True, created_at__date__gte=start, created_at__date__lte=end)
    spa = SpaOrder.objects.filter(is_paid=True, created_at__date__gte=start, created_at__date__lte=end)
    expenses = Expense.objects.filter(spent_on__gte=start, spent_on__lte=end)
    kitchen_usage = IngredientUsage.objects.filter(used_on__gte=start, used_on__lte=end)

    if active:
        bookings = bookings.filter(branch=active)
        food = food.filter(booking__branch=active)
        bar = bar.filter(booking__branch=active)
        laundry = laundry.filter(booking__branch=active)
        spa = spa.filter(booking__branch=active)
        expenses = expenses.filter(branch=active)
        kitchen_usage = kitchen_usage.filter(Q(branch=active) | Q(branch__isnull=True))

    bookings_total = bookings.aggregate(Sum('total_amount'))['total_amount__sum'] or Decimal('0')
    food_total = food.aggregate(Sum('total_price'))['total_price__sum'] or Decimal('0')
    bar_total = bar.aggregate(Sum('total_price'))['total_price__sum'] or Decimal('0')
    laundry_total = laundry.aggregate(Sum('total_price'))['total_price__sum'] or Decimal('0')
    spa_total = spa.aggregate(Sum('total_price'))['total_price__sum'] or Decimal('0')

    # Bar gross profit (sale price - cost price) for served/paid items.
    bar_profit = Decimal('0')
    bar_items = BarOrderItem.objects.filter(order__in=bar).select_related('drink')
    for item in bar_items:
        cost = item.drink.cost_price if item.drink else Decimal('0')
        bar_profit += (item.price - (cost or Decimal('0'))) * item.quantity

    # Laundry gross profit (sale price - cost price).
    laundry_profit = Decimal('0')
    laundry_items = LaundryOrderItem.objects.filter(order__in=laundry).select_related('service')
    for item in laundry_items:
        cost = item.service.cost_price if item.service else Decimal('0')
        laundry_profit += (item.price - (cost or Decimal('0'))) * item.quantity

    spa_profit = Decimal('0')
    spa_items = SpaOrderItem.objects.filter(order__in=spa).select_related('service')
    for item in spa_items:
        cost = item.service.cost_price if item.service else Decimal('0')
        spa_profit += (item.price - (cost or Decimal('0'))) * item.quantity

    expenses_total = expenses.aggregate(Sum('amount'))['amount__sum'] or Decimal('0')
    kitchen_cost = sum((u.total_cost for u in kitchen_usage), Decimal('0'))

    combined_revenue = bookings_total + food_total + bar_total + laundry_total + spa_total
    # Subtract direct kitchen ingredient cost so the report reflects true profit.
    net = combined_revenue - expenses_total - kitchen_cost

    # Expense breakdown by category
    category_breakdown = expenses.values('category').annotate(total=Sum('amount')).order_by('-total')
    cat_labels = dict(Expense.CATEGORY_CHOICES)
    category_breakdown = [
        {'label': cat_labels.get(c['category'], c['category']), 'total': c['total']}
        for c in category_breakdown
    ]

    # Year / month options for the historical selector.
    current_year = timezone.now().date().year
    year_choices = list(range(current_year, current_year - 6, -1))
    month_choices = [(i, date(2000, i, 1).strftime('%B')) for i in range(1, 13)]

    context = {
        'period': period,
        'period_label': label,
        'start': start,
        'end': end,
        'bookings_total': _money(bookings_total),
        'food_total': _money(food_total),
        'bar_total': _money(bar_total),
        'bar_profit': _money(bar_profit),
        'laundry_total': _money(laundry_total),
        'laundry_profit': _money(laundry_profit),
        'spa_total': _money(spa_total),
        'spa_profit': _money(spa_profit),
        'kitchen_cost': _money(kitchen_cost),
        'combined_revenue': _money(combined_revenue),
        'expenses_total': _money(expenses_total),
        'net': _money(net),
        'is_profit': net >= 0,
        'net_abs': _money(abs(net)),
        'category_breakdown': category_breakdown,
        'active_branch': active,
        'base_template': _panel_base(request),
        'year_choices': year_choices,
        'month_choices': month_choices,
        'sel_year': (request.GET.get('year') or '').strip(),
        'sel_month': (request.GET.get('month') or '').strip(),
        'sel_day': (request.GET.get('day') or '').strip(),
    }
    return render(request, 'admin_panel/accounting.html', context)


# ===========================================================================
# GLOBAL SEARCH (top search bar)
# ===========================================================================
@login_required
def global_search(request):
    if request.user.role not in ('admin', 'employee'):
        return redirect('home')

    q = (request.GET.get('q') or '').strip()
    rooms = guests = staff = bookings = drinks = food = []
    if q:
        rooms = Room.objects.filter(
            Q(room_number__icontains=q) | Q(room_type__icontains=q) | Q(description__icontains=q)
        )[:25]
        guests = Customer.objects.select_related('user').filter(
            Q(user__username__icontains=q) | Q(user__first_name__icontains=q) |
            Q(user__last_name__icontains=q) | Q(user__email__icontains=q) | Q(user__mobile__icontains=q)
        )[:25]
        staff = Employee.objects.select_related('user').filter(
            Q(user__username__icontains=q) | Q(user__first_name__icontains=q) |
            Q(user__last_name__icontains=q) | Q(job_type__icontains=q) | Q(id_card_number__icontains=q)
        )[:25]
        bookings = Booking.objects.select_related('user', 'room').filter(
            Q(user__username__icontains=q) | Q(user__first_name__icontains=q) |
            Q(user__last_name__icontains=q) | Q(room__room_number__icontains=q)
        ).order_by('-id')[:25]
        drinks = Drink.objects.filter(Q(name__icontains=q) | Q(category__icontains=q))[:25]
        food = FoodItem.objects.filter(Q(name__icontains=q) | Q(category__icontains=q))[:25]

    total = len(rooms) + len(guests) + len(staff) + len(bookings) + len(drinks) + len(food)
    return render(request, 'admin_panel/search_results.html', {
        'q': q,
        'rooms': rooms,
        'guests': guests,
        'staff': staff,
        'bookings': bookings,
        'drinks': drinks,
        'food': food,
        'total': total,
        'base_template': _panel_base(request),
    })


# ===========================================================================
# KITCHEN INGREDIENT INVENTORY
# ===========================================================================
@login_required
@employee_required(allowed_jobs=['kitchen', 'manager'])
def ingredient_inventory(request):
    active = _scope_branch(request)
    # Generate low-stock / expiry alerts for the kitchen + admin/manager bells.
    scan_inventory_alerts(active)
    ingredients = Ingredient.objects.all().order_by('name')
    if active:
        ingredients = _branch_menu_filter(ingredients, active)
    page_obj = paginate(request, ingredients)
    return render(request, 'kitchen_panel/inventory.html', {
        'ingredients': page_obj, 'page_obj': page_obj,
        'active_branch': active, 'base_template': _panel_base(request),
    })


@login_required
@employee_required(allowed_jobs=['kitchen', 'manager'])
def add_ingredient(request):
    active = _active_branch(request)
    if request.method == 'POST':
        form = IngredientForm(request.POST)
        if form.is_valid():
            ing = form.save(commit=False)
            if not ing.branch_id:
                ing.branch = active or _default_branch()
            ing.save()
            log_action(request, action='create', module='Ingredient',
                       summary=f"Added ingredient {ing.name}", object=ing, branch=ing.branch)
            messages.success(request, f"Ingredient '{ing.name}' added to inventory.")
            return redirect('ingredient_inventory')
    else:
        form = IngredientForm(initial={'branch': active} if active else None)
    return render(request, 'kitchen_panel/ingredient_form.html', {
        'form': form, 'title': 'Add Ingredient', 'base_template': _panel_base(request),
    })


@login_required
@employee_required(allowed_jobs=['kitchen', 'manager'])
def edit_ingredient(request, ingredient_id):
    ing = get_object_or_404(Ingredient, id=ingredient_id)
    if request.method == 'POST':
        form = IngredientForm(request.POST, instance=ing)
        if form.is_valid():
            form.save()
            log_action(request, action='update', module='Ingredient',
                       summary=f"Updated ingredient {ing.name}", object=ing, branch=ing.branch)
            messages.success(request, f"{ing.name} updated.")
            return redirect('ingredient_inventory')
    else:
        form = IngredientForm(instance=ing)
    return render(request, 'kitchen_panel/ingredient_form.html', {
        'form': form, 'title': 'Edit Ingredient', 'base_template': _panel_base(request),
    })


@login_required
@employee_required(allowed_jobs=['kitchen', 'manager'])
def delete_ingredient(request, ingredient_id):
    ing = get_object_or_404(Ingredient, id=ingredient_id)
    name = ing.name
    branch = ing.branch
    log_action(request, action='delete', module='Ingredient',
               summary=f"Deleted ingredient {name}", object=ing, branch=branch)
    ing.delete()
    messages.success(request, f"{name} removed from inventory.")
    return redirect('ingredient_inventory')


@login_required
@employee_required(allowed_jobs=['kitchen', 'manager'])
def restock_ingredient(request, ingredient_id):
    ing = get_object_or_404(Ingredient, id=ingredient_id)
    if request.method == 'POST':
        form = IngredientRestockForm(request.POST)
        if form.is_valid():
            qty = form.cleaned_data['quantity']
            note = form.cleaned_data['note'] or "Manual restock"
            ing.stock_quantity += qty
            ing.save()
            IngredientStockTransaction.objects.create(ingredient=ing, quantity=qty, note=note)
            log_action(request, action='update', module='Ingredient',
                       summary=f"Restocked {ing.name} by {qty} {ing.unit}",
                       object=ing, branch=ing.branch)
            messages.success(request, f"Restocked {qty} {ing.unit} of {ing.name}.")
            return redirect('ingredient_inventory')
    else:
        form = IngredientRestockForm()
    return render(request, 'kitchen_panel/ingredient_restock.html', {
        'form': form, 'ingredient': ing, 'base_template': _panel_base(request),
    })


# ===========================================================================
# CSV IMPORT / EXPORT  (Bar drinks + Kitchen ingredients)
# ===========================================================================
DRINK_CSV_HEADERS = ['name', 'category', 'cost_price', 'price', 'stock_quantity',
                     'low_stock_threshold', 'expiry_date', 'is_available']
INGREDIENT_CSV_HEADERS = ['name', 'unit', 'cost_price', 'stock_quantity',
                          'low_stock_threshold', 'expiry_date']


def _csv_response(filename, headers, rows):
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    writer = csv.writer(response)
    writer.writerow(headers)
    for row in rows:
        writer.writerow(row)
    return response


@login_required
@employee_required(allowed_jobs=['bar', 'manager'])
def export_drinks_csv(request):
    active = _scope_branch(request)
    drinks = Drink.objects.all().order_by('name')
    if active:
        drinks = _branch_menu_filter(drinks, active)
    rows = [[d.name, d.category, d.cost_price, d.price, d.stock_quantity,
             d.low_stock_threshold, d.expiry_date or '', 'yes' if d.is_available else 'no']
            for d in drinks]
    return _csv_response('bar_products.csv', DRINK_CSV_HEADERS, rows)


@login_required
@employee_required(allowed_jobs=['bar', 'manager'])
def drink_csv_template(request):
    sample = [['Coca Cola', 'soft', '0.50', '1.50', '24', '5', '2026-12-31', 'yes']]
    return _csv_response('bar_products_template.csv', DRINK_CSV_HEADERS, sample)


@login_required
@employee_required(allowed_jobs=['bar', 'manager'])
def import_drinks_csv(request):
    active = _active_branch(request)
    if request.method == 'POST':
        form = CSVImportForm(request.POST, request.FILES)
        if form.is_valid():
            created, updated, errors = _import_drinks(form.cleaned_data['csv_file'],
                                                       active or _default_branch())
            messages.success(request, f"Import complete: {created} added, {updated} updated.")
            if errors:
                messages.warning(request, f"{len(errors)} row(s) skipped: " + "; ".join(errors[:5]))
            return redirect('bar_inventory')
    else:
        form = CSVImportForm()
    return render(request, 'admin_panel/csv_import.html', {
        'form': form,
        'title': 'Import Bar Products',
        'template_url': 'drink_csv_template',
        'cancel_url': 'bar_inventory',
        'headers': DRINK_CSV_HEADERS,
        'base_template': _panel_base(request),
    })


def _import_drinks(uploaded_file, branch):
    created = updated = 0
    errors = []
    decoded = io.TextIOWrapper(uploaded_file.file, encoding='utf-8-sig', errors='ignore')
    reader = csv.DictReader(decoded)
    for i, row in enumerate(reader, start=2):
        name = (row.get('name') or '').strip()
        if not name:
            continue
        try:
            defaults = {
                'category': (row.get('category') or 'soft').strip() or 'soft',
                'cost_price': Decimal(str(row.get('cost_price') or '0') or '0'),
                'price': Decimal(str(row.get('price') or '0') or '0'),
                'stock_quantity': int(float(row.get('stock_quantity') or 0)),
                'low_stock_threshold': int(float(row.get('low_stock_threshold') or 5)),
            }
            expiry = (row.get('expiry_date') or '').strip()
            if expiry:
                defaults['expiry_date'] = date.fromisoformat(expiry)
            avail = (row.get('is_available') or 'yes').strip().lower()
            defaults['is_available'] = avail in ('yes', 'true', '1', 'y')

            obj, was_created = Drink.objects.get_or_create(
                name=name, branch=branch, defaults=defaults)
            if was_created:
                created += 1
            else:
                for k, v in defaults.items():
                    setattr(obj, k, v)
                obj.save()
                updated += 1
        except Exception as exc:
            errors.append(f"row {i}: {exc}")
    return created, updated, errors


@login_required
@employee_required(allowed_jobs=['kitchen', 'manager'])
def export_ingredients_csv(request):
    active = _scope_branch(request)
    ingredients = Ingredient.objects.all().order_by('name')
    if active:
        ingredients = _branch_menu_filter(ingredients, active)
    rows = [[i.name, i.unit, i.cost_price, i.stock_quantity, i.low_stock_threshold,
             i.expiry_date or ''] for i in ingredients]
    return _csv_response('kitchen_ingredients.csv', INGREDIENT_CSV_HEADERS, rows)


@login_required
@employee_required(allowed_jobs=['kitchen', 'manager'])
def ingredient_csv_template(request):
    sample = [['Tomatoes', 'kg', '1.20', '30', '5', '2026-07-15']]
    return _csv_response('kitchen_ingredients_template.csv', INGREDIENT_CSV_HEADERS, sample)


@login_required
@employee_required(allowed_jobs=['kitchen', 'manager'])
def import_ingredients_csv(request):
    active = _active_branch(request)
    if request.method == 'POST':
        form = CSVImportForm(request.POST, request.FILES)
        if form.is_valid():
            created, updated, errors = _import_ingredients(form.cleaned_data['csv_file'],
                                                           active or _default_branch())
            messages.success(request, f"Import complete: {created} added, {updated} updated.")
            if errors:
                messages.warning(request, f"{len(errors)} row(s) skipped: " + "; ".join(errors[:5]))
            return redirect('ingredient_inventory')
    else:
        form = CSVImportForm()
    return render(request, 'admin_panel/csv_import.html', {
        'form': form,
        'title': 'Import Kitchen Ingredients',
        'template_url': 'ingredient_csv_template',
        'cancel_url': 'ingredient_inventory',
        'headers': INGREDIENT_CSV_HEADERS,
        'base_template': _panel_base(request),
    })


def _import_ingredients(uploaded_file, branch):
    created = updated = 0
    errors = []
    decoded = io.TextIOWrapper(uploaded_file.file, encoding='utf-8-sig', errors='ignore')
    reader = csv.DictReader(decoded)
    for i, row in enumerate(reader, start=2):
        name = (row.get('name') or '').strip()
        if not name:
            continue
        try:
            defaults = {
                'unit': (row.get('unit') or 'pcs').strip() or 'pcs',
                'cost_price': Decimal(str(row.get('cost_price') or '0') or '0'),
                'stock_quantity': Decimal(str(row.get('stock_quantity') or '0') or '0'),
                'low_stock_threshold': Decimal(str(row.get('low_stock_threshold') or '5') or '5'),
            }
            expiry = (row.get('expiry_date') or '').strip()
            if expiry:
                defaults['expiry_date'] = date.fromisoformat(expiry)

            obj, was_created = Ingredient.objects.get_or_create(
                name=name, branch=branch, defaults=defaults)
            if was_created:
                created += 1
            else:
                for k, v in defaults.items():
                    setattr(obj, k, v)
                obj.save()
                updated += 1
        except Exception as exc:
            errors.append(f"row {i}: {exc}")
    return created, updated, errors


# ===========================================================================
# LAUNDRY MODULE
# ===========================================================================
@login_required
@customer_required
def order_laundry(request):
    active_booking = _active_booking_for(request.user)
    if not active_booking:
        messages.error(request, "You must be checked into a room to order laundry.")
        return redirect('customer_dashboard')

    services = _branch_menu_filter(LaundryService.objects.filter(is_available=True), active_booking.branch)
    wallet = _get_wallet(request.user)

    if request.method == 'POST':
        order = LaundryOrder.objects.create(booking=active_booking, branch=active_booking.branch)
        subtotal = Decimal('0')
        any_item = False
        for s in services:
            qty = int(request.POST.get(f'qty_{s.id}', 0) or 0)
            if qty > 0:
                LaundryOrderItem.objects.create(order=order, service=s, quantity=qty, price=s.price)
                subtotal += qty * s.price
                any_item = True

        if not any_item:
            order.delete()
            messages.error(request, "Please select at least one laundry service.")
            return redirect('order_laundry')

        vat_rate, vat_amount, total = _apply_vat(subtotal)
        order.total_price = total

        if request.POST.get('pay_method') == 'wallet':
            if wallet.balance >= total:
                wallet.debit(total, reason=f"Laundry Order #{order.id}")
                order.is_paid = True
                messages.success(request, f"Laundry order placed and {_money(total)} paid from your wallet!")
            else:
                messages.warning(
                    request,
                    f"Insufficient wallet balance ({_money(wallet.balance)}). The order ({_money(total)}) was added to "
                    f"your room bill — top up your wallet or settle it at checkout."
                )
        else:
            messages.success(request, "Laundry order placed! It has been added to your room bill.")

        order.save()
        notify.notify_roles(
            ['admin', 'manager', 'receptionist', 'housekeeping'], 'new_laundry_order',
            'New laundry order',
            f"Room {active_booking.room.room_number} placed a laundry order ({_money(total)}).",
            link='/dashboard/laundry/', branch=active_booking.branch,
        )
        return redirect('customer_laundry_history')

    return render(request, 'customer_panel/order_laundry.html', {
        'services': services, 'room': active_booking.room, 'wallet': wallet,
    })


@login_required
@customer_required
def customer_laundry_history(request):
    orders = LaundryOrder.objects.filter(booking__user=request.user).prefetch_related('items__service').order_by('-created_at')
    page_obj = paginate(request, orders)
    return render(request, 'customer_panel/laundry_history.html', {'orders': page_obj, 'page_obj': page_obj})


@login_required
@customer_required
def pay_laundry_wallet(request, order_id):
    order = get_object_or_404(LaundryOrder, id=order_id, booking__user=request.user)
    if order.is_paid:
        messages.info(request, "This laundry order is already paid.")
        return redirect('customer_laundry_history')
    wallet = _get_wallet(request.user)
    if wallet.balance >= order.total_price:
        wallet.debit(order.total_price, reason=f"Laundry Order #{order.id}")
        order.is_paid = True
        order.save()
        messages.success(request, f"{_money(order.total_price)} paid from your wallet.")
    else:
        messages.error(request, f"Insufficient wallet balance ({_money(wallet.balance)}).")
    return redirect('customer_laundry_history')


@login_required
@employee_required(allowed_jobs=['housekeeping', 'receptionist', 'manager'])
def laundry_monitor(request):
    scope = _scope_branch(request)
    orders = LaundryOrder.objects.select_related('booking__room', 'booking__user').prefetch_related('items__service').order_by('-created_at')
    if scope:
        orders = orders.filter(booking__branch=scope)
    page_obj = paginate(request, orders)
    revenue = orders.filter(is_paid=True).aggregate(Sum('total_price'))['total_price__sum'] or 0
    return render(request, 'housekeeping_panel/laundry_monitor.html', {
        'orders': page_obj, 'page_obj': page_obj,
        'revenue': _money(revenue), 'base_template': _panel_base(request),
    })


@login_required
@employee_required(allowed_jobs=['housekeeping', 'receptionist', 'manager'])
def update_laundry_status(request, order_id, status):
    order = get_object_or_404(LaundryOrder, id=order_id)
    if status in dict(LaundryOrder.STATUS_CHOICES):
        order.status = status
        if hasattr(request.user, 'employee_profile'):
            order.handled_by = request.user.employee_profile
        order.save()
        log_action(request, action='status', module='LaundryOrder',
                   summary=f"Laundry order #{order.id} -> {order.get_status_display()}",
                   object=order, branch=order.branch)
        messages.success(request, f"Laundry order #{order.id} marked as {order.get_status_display()}.")
    return redirect('laundry_monitor')


@login_required
@employee_required(allowed_jobs=['housekeeping', 'receptionist', 'manager'])
def mark_laundry_paid(request, order_id):
    order = get_object_or_404(LaundryOrder, id=order_id)
    order.is_paid = True
    if hasattr(request.user, 'employee_profile'):
        order.handled_by = request.user.employee_profile
    order.save()
    log_action(request, action='payment', module='LaundryOrder',
               summary=f"Laundry order #{order.id} marked paid", object=order, branch=order.branch)
    messages.success(request, f"Laundry order #{order.id} marked as paid.")
    return redirect('laundry_monitor')


# ---- Laundry service menu management (Admin / Manager) ----
@login_required
def laundry_services(request):
    if not _can_manage_wallet(request.user):
        return redirect('home')
    active = _scope_branch(request)
    services = LaundryService.objects.all()
    if active:
        services = _branch_menu_filter(services, active)
    page_obj = paginate(request, services)
    return render(request, 'admin_panel/laundry_services.html', {
        'services': page_obj, 'page_obj': page_obj, 'base_template': _panel_base(request),
    })


@login_required
def add_laundry_service(request):
    if not _can_manage_wallet(request.user):
        return redirect('home')
    active = _active_branch(request)
    if request.method == 'POST':
        form = LaundryServiceForm(request.POST)
        if form.is_valid():
            svc = form.save(commit=False)
            if not svc.branch_id:
                svc.branch = active or _default_branch()
            svc.save()
            messages.success(request, f"Laundry service '{svc.name}' added.")
            return redirect('laundry_services')
    else:
        form = LaundryServiceForm(initial={'branch': active} if active else None)
    return render(request, 'admin_panel/laundry_service_form.html', {
        'form': form, 'title': 'Add Laundry Service', 'base_template': _panel_base(request),
    })


@login_required
def edit_laundry_service(request, service_id):
    if not _can_manage_wallet(request.user):
        return redirect('home')
    svc = get_object_or_404(LaundryService, id=service_id)
    if request.method == 'POST':
        form = LaundryServiceForm(request.POST, instance=svc)
        if form.is_valid():
            form.save()
            messages.success(request, f"{svc.name} updated.")
            return redirect('laundry_services')
    else:
        form = LaundryServiceForm(instance=svc)
    return render(request, 'admin_panel/laundry_service_form.html', {
        'form': form, 'title': 'Edit Laundry Service', 'base_template': _panel_base(request),
    })


@login_required
def delete_laundry_service(request, service_id):
    if not _can_manage_wallet(request.user):
        return redirect('home')
    svc = get_object_or_404(LaundryService, id=service_id)
    name = svc.name
    svc.delete()
    messages.success(request, f"{name} removed.")
    return redirect('laundry_services')


# ===========================================================================
# ROOM IMAGE GALLERY
# ===========================================================================
@login_required
@admin_required
def manage_room_images(request, room_id):
    room = get_object_or_404(Room, id=room_id)
    if request.method == 'POST':
        form = RoomImageForm(request.POST, request.FILES)
        if form.is_valid():
            img = form.save(commit=False)
            img.room = room
            img.save()
            messages.success(request, "Image added to the room gallery.")
            return redirect('manage_room_images', room_id=room.id)
    else:
        form = RoomImageForm()
    return render(request, 'admin_panel/room_images.html', {
        'room': room, 'form': form, 'images': room.gallery.all(),
        'base_template': _panel_base(request),
    })


@login_required
@admin_required
def delete_room_image(request, image_id):
    img = get_object_or_404(RoomImage, id=image_id)
    room_id = img.room_id
    img.delete()
    messages.success(request, "Image removed from gallery.")
    return redirect('manage_room_images', room_id=room_id)


# ===========================================================================
# CMS: editable Home + About Us content
# ===========================================================================
@login_required
@admin_required
def site_content(request):
    settings_obj = SiteSetting.load()
    if request.method == 'POST':
        form = SiteContentForm(request.POST, request.FILES, instance=settings_obj)
        if form.is_valid():
            form.save()
            messages.success(request, "Home & About page content updated.")
            return redirect('site_content')
    else:
        form = SiteContentForm(instance=settings_obj)
    return render(request, 'admin_panel/site_content.html', {'form': form, 'settings': settings_obj})


# ===========================================================================
# NOTIFICATIONS (bell icon)
# ===========================================================================
@login_required
def notifications_feed(request):
    """JSON feed used by the bell icon to poll + play a sound on new alerts."""
    qs = Notification.objects.filter(recipient=request.user)
    unread = qs.filter(is_read=False)
    data = [{
        'id': n.id,
        'type': n.notif_type,
        'title': n.title,
        'body': n.body,
        'link': n.link,
        'icon': n.icon,
        'is_read': n.is_read,
        'ago': timezone.localtime(n.created_at).strftime('%b %d, %H:%M'),
    } for n in qs[:15]]
    return JsonResponse({'unread': unread.count(), 'items': data})


@login_required
def notifications_page(request):
    qs = Notification.objects.filter(recipient=request.user)
    page_obj = paginate(request, qs, per_page=20)
    return render(request, 'common/notifications.html', {
        'notifications': page_obj, 'page_obj': page_obj,
        'base_template': _panel_base(request),
    })


@login_required
def mark_notifications_read(request):
    Notification.objects.filter(recipient=request.user, is_read=False).update(is_read=True)
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return JsonResponse({'ok': True})
    return redirect('notifications_page')


@login_required
def open_notification(request, notif_id):
    n = get_object_or_404(Notification, id=notif_id, recipient=request.user)
    n.is_read = True
    n.save()
    return redirect(n.link or 'notifications_page')


def scan_inventory_alerts(branch=None):
    """
    Generate expiration + low-stock alerts for bar drinks and kitchen ingredients.
    De-duplicated so the same unread alert isn't created repeatedly. Safe to call
    on dashboard loads.
    """
    drinks = Drink.objects.all()
    ingredients = Ingredient.objects.all()
    if branch is not None:
        drinks = _branch_menu_filter(drinks, branch)
        ingredients = _branch_menu_filter(ingredients, branch)

    for d in drinks:
        if d.is_expired:
            notify.notify_roles(['admin', 'manager', 'bar'], 'bar_expiry',
                                f"Expired: {d.name}",
                                f"{d.name} expired on {d.expiry_date:%b %d, %Y}.",
                                link='/dashboard/bar/inventory/', branch=d.branch, dedupe=True)
        elif d.is_expiring_soon:
            notify.notify_roles(['admin', 'manager', 'bar'], 'bar_expiry',
                                f"Expiring soon: {d.name}",
                                f"{d.name} expires on {d.expiry_date:%b %d, %Y}.",
                                link='/dashboard/bar/inventory/', branch=d.branch, dedupe=True)
        if d.is_low_stock:
            notify.notify_roles(['admin', 'manager', 'bar'], 'low_stock',
                                f"Low stock: {d.name}",
                                f"Only {d.stock_quantity} left — due for restock.",
                                link='/dashboard/bar/inventory/', branch=d.branch, dedupe=True)

    for ing in ingredients:
        if ing.is_low_stock:
            notify.notify_roles(['admin', 'manager', 'kitchen'], 'low_stock',
                                f"Low stock: {ing.name}",
                                f"Only {ing.stock_quantity} {ing.unit} left — due for restock.",
                                link='/dashboard/kitchen/inventory/', branch=ing.branch, dedupe=True)
        if ing.is_expired:
            notify.notify_roles(['admin', 'manager', 'kitchen'], 'low_stock',
                                f"Expired ingredient: {ing.name}",
                                f"{ing.name} expired on {ing.expiry_date:%b %d, %Y}.",
                                link='/dashboard/kitchen/inventory/', branch=ing.branch, dedupe=True)


# ===========================================================================
# PRODUCT HISTORY  (Drinks + Ingredients)
# ===========================================================================
@login_required
@employee_required(allowed_jobs=['bar', 'manager'])
def drink_history(request, drink_id):
    """Full history of sales / restock / adjustments for a single drink."""
    drink = get_object_or_404(Drink, id=drink_id)

    # Restock + adjustment log
    txns = drink.stock_transactions.all().order_by('-created_at')

    # Sale entries derived from bar order items (each sale also has a
    # StockTransaction record, but we surface the order id for clarity).
    sale_items = BarOrderItem.objects.filter(drink=drink).select_related('order').order_by('-order__created_at')

    # Build a combined timeline.
    timeline = []
    for t in txns:
        timeline.append({
            'when': t.created_at,
            'type': 'restock' if t.quantity > 0 else 'sale',
            'qty': t.quantity,
            'note': t.note or '',
        })
    # Tally running balance backwards (best-effort, since we don't snapshot a
    # historical stock value — current stock is the trustworthy source).
    total_in = sum(t.quantity for t in txns if t.quantity > 0)
    total_out = sum(-t.quantity for t in txns if t.quantity < 0)
    return render(request, 'bar_panel/drink_history.html', {
        'drink': drink, 'txns': txns, 'sale_items': sale_items,
        'total_in': total_in, 'total_out': total_out,
        'base_template': _panel_base(request),
    })


@login_required
@employee_required(allowed_jobs=['kitchen', 'manager'])
def ingredient_history(request, ingredient_id):
    """Full history of restock + usage for a single ingredient."""
    ing = get_object_or_404(Ingredient, id=ingredient_id)
    txns = ing.stock_transactions.all().order_by('-created_at')
    usages = ing.usages.all().order_by('-used_on', '-id')
    total_restocked = sum((t.quantity for t in txns if t.quantity > 0), Decimal('0'))
    total_used = sum((u.quantity for u in usages), Decimal('0'))
    return render(request, 'kitchen_panel/ingredient_history.html', {
        'ingredient': ing,
        'txns': txns,
        'usages': usages,
        'total_restocked': total_restocked,
        'total_used': total_used,
        'base_template': _panel_base(request),
    })


# ===========================================================================
# KITCHEN INGREDIENT USAGE TRACKER
# ===========================================================================
def _parse_iso_date(value):
    try:
        return date.fromisoformat((value or '').strip())
    except (ValueError, TypeError):
        return None


@login_required
@employee_required(allowed_jobs=['kitchen', 'manager'])
def kitchen_usage_list(request):
    """List + filter ingredient usage records."""
    scope = _scope_branch(request)

    qs = IngredientUsage.objects.select_related('ingredient', 'used_by').all()
    if scope is not None:
        qs = qs.filter(Q(branch=scope) | Q(branch__isnull=True))

    # Filters
    sel_start = (request.GET.get('start') or '').strip()
    sel_end = (request.GET.get('end') or '').strip()
    sel_year = (request.GET.get('year') or '').strip()
    sel_month = (request.GET.get('month') or '').strip()
    sel_ingredient = (request.GET.get('ingredient') or '').strip()

    start_date = _parse_iso_date(sel_start)
    end_date = _parse_iso_date(sel_end)

    if start_date:
        qs = qs.filter(used_on__gte=start_date)
    if end_date:
        qs = qs.filter(used_on__lte=end_date)
    if sel_year.isdigit():
        qs = qs.filter(used_on__year=int(sel_year))
    if sel_month.isdigit() and 1 <= int(sel_month) <= 12:
        qs = qs.filter(used_on__month=int(sel_month))
    if sel_ingredient.isdigit():
        qs = qs.filter(ingredient_id=int(sel_ingredient))

    qs = qs.order_by('-used_on', '-id')
    page_obj = paginate(request, qs, per_page=20)

    total_quantity = qs.aggregate(s=Sum('quantity'))['s'] or Decimal('0')
    total_cost = sum((u.total_cost for u in qs), Decimal('0'))

    ingredients_qs = Ingredient.objects.all().order_by('name')
    if scope is not None:
        ingredients_qs = _branch_menu_filter(ingredients_qs, scope)

    current_year = timezone.now().date().year
    year_choices = list(range(current_year, current_year - 6, -1))
    month_choices = [(i, date(2000, i, 1).strftime('%B')) for i in range(1, 13)]

    return render(request, 'kitchen_panel/usage_list.html', {
        'usages': page_obj,
        'page_obj': page_obj,
        'total_quantity': total_quantity,
        'total_cost': _money(total_cost),
        'ingredients': ingredients_qs,
        'sel_start': sel_start,
        'sel_end': sel_end,
        'sel_year': sel_year,
        'sel_month': sel_month,
        'sel_ingredient': sel_ingredient,
        'year_choices': year_choices,
        'month_choices': month_choices,
        'base_template': _panel_base(request),
    })


@login_required
@employee_required(allowed_jobs=['kitchen', 'manager'])
def kitchen_usage_add(request):
    scope = _scope_branch(request)
    if request.method == 'POST':
        form = IngredientUsageForm(request.POST, branch=scope)
        if form.is_valid():
            usage = form.save(commit=False)
            usage.unit_cost = usage.ingredient.cost_price or Decimal('0')
            usage.used_by = request.user
            usage.branch = usage.ingredient.branch or scope
            # Reduce inventory stock (but never go below zero)
            ing = usage.ingredient
            if usage.quantity > ing.stock_quantity:
                messages.warning(request,
                                 f"Recorded usage exceeds current stock ({ing.stock_quantity} {ing.unit}). "
                                 "Stock will be set to 0.")
                ing.stock_quantity = Decimal('0')
            else:
                ing.stock_quantity = ing.stock_quantity - usage.quantity
            ing.save()
            usage.save()
            # Log a negative stock transaction too, so it appears in History.
            IngredientStockTransaction.objects.create(
                ingredient=ing, quantity=-usage.quantity,
                note=f"Used in kitchen ({usage.note or 'daily usage'})")
            log_action(request, action='update', module='IngredientUsage',
                       summary=f"Used {usage.quantity} {ing.unit} of {ing.name}",
                       object=usage, branch=usage.branch)
            messages.success(request, f"Logged {usage.quantity} {ing.unit} of {ing.name} as used.")
            return redirect('kitchen_usage_list')
    else:
        form = IngredientUsageForm(initial={'used_on': timezone.now().date()}, branch=scope)
    return render(request, 'kitchen_panel/usage_form.html', {
        'form': form, 'title': 'Record Ingredient Usage',
        'base_template': _panel_base(request),
    })


@login_required
@employee_required(allowed_jobs=['kitchen', 'manager'])
def kitchen_usage_delete(request, usage_id):
    usage = get_object_or_404(IngredientUsage, id=usage_id)
    # Refund the stock back to the ingredient.
    ing = usage.ingredient
    ing.stock_quantity = (ing.stock_quantity or Decimal('0')) + (usage.quantity or Decimal('0'))
    ing.save()
    IngredientStockTransaction.objects.create(
        ingredient=ing, quantity=usage.quantity,
        note=f"Reversed kitchen usage #{usage.id}")
    log_action(request, action='delete', module='IngredientUsage',
               summary=f"Reversed {usage.quantity} {ing.unit} usage of {ing.name}",
               object=usage, branch=usage.branch)
    usage.delete()
    messages.success(request, "Usage record reversed and stock refunded.")
    return redirect('kitchen_usage_list')


# ===========================================================================
# SPA MODULE
# ===========================================================================
def _can_monitor_spa(user):
    if not user.is_authenticated:
        return False
    if user.role == 'admin':
        return True
    if user.role == 'employee' and hasattr(user, 'employee_profile'):
        return user.employee_profile.job_type in ('manager', 'receptionist', 'spa')
    return False


@login_required
@customer_required
def order_spa(request):
    active_booking = _active_booking_for(request.user)
    if not active_booking:
        messages.error(request, "You must be checked into a room to book spa services.")
        return redirect('customer_dashboard')

    services = _branch_menu_filter(SpaService.objects.filter(is_available=True),
                                   active_booking.branch)
    wallet = _get_wallet(request.user)

    if request.method == 'POST':
        order = SpaOrder.objects.create(booking=active_booking, branch=active_booking.branch)
        subtotal = Decimal('0')
        any_item = False
        for s in services:
            qty = int(request.POST.get(f'qty_{s.id}', 0) or 0)
            if qty > 0:
                SpaOrderItem.objects.create(order=order, service=s, quantity=qty, price=s.price)
                subtotal += qty * s.price
                any_item = True

        if not any_item:
            order.delete()
            messages.error(request, "Please select at least one spa service.")
            return redirect('order_spa')

        appointment = (request.POST.get('appointment_at') or '').strip()
        if appointment:
            try:
                order.appointment_at = timezone.datetime.fromisoformat(appointment)
            except (ValueError, TypeError):
                pass
        order.note = (request.POST.get('note') or '').strip()[:255]

        _, _, total = _apply_vat(subtotal)
        order.total_price = total

        if request.POST.get('pay_method') == 'wallet':
            if wallet.balance >= total:
                wallet.debit(total, reason=f"Spa Order #{order.id}")
                order.is_paid = True
                messages.success(request, f"Spa order placed and {_money(total)} paid from your wallet!")
            else:
                messages.warning(
                    request,
                    f"Insufficient wallet balance ({_money(wallet.balance)}). The order ({_money(total)}) was added to "
                    f"your room bill — top up your wallet or settle it at checkout."
                )
        else:
            messages.success(request, "Spa order placed! It has been added to your room bill.")

        order.save()
        notify.notify_roles(
            ['admin', 'manager', 'receptionist', 'spa'], 'new_spa_order',
            'New spa order',
            f"Room {active_booking.room.room_number} placed a spa order ({_money(total)}).",
            link='/dashboard/spa/monitor/', branch=active_booking.branch,
        )
        log_action(request, action='create', module='SpaOrder',
                   summary=f"Guest placed spa order ({_money(total)})", object=order,
                   branch=active_booking.branch)
        return redirect('customer_spa_history')

    return render(request, 'customer_panel/order_spa.html', {
        'services': services, 'room': active_booking.room, 'wallet': wallet,
    })


@login_required
@customer_required
def customer_spa_history(request):
    orders = SpaOrder.objects.filter(booking__user=request.user)\
        .prefetch_related('items__service').order_by('-created_at')
    page_obj = paginate(request, orders)
    return render(request, 'customer_panel/spa_history.html', {
        'orders': page_obj, 'page_obj': page_obj,
    })


@login_required
@customer_required
def pay_spa_wallet(request, order_id):
    order = get_object_or_404(SpaOrder, id=order_id, booking__user=request.user)
    if order.is_paid:
        messages.info(request, "This spa order is already paid.")
        return redirect('customer_spa_history')
    wallet = _get_wallet(request.user)
    if wallet.balance >= order.total_price:
        wallet.debit(order.total_price, reason=f"Spa Order #{order.id}")
        order.is_paid = True
        order.save()
        messages.success(request, f"{_money(order.total_price)} paid from your wallet.")
    else:
        messages.error(request, f"Insufficient wallet balance ({_money(wallet.balance)}).")
    return redirect('customer_spa_history')


@login_required
def spa_monitor(request):
    if not _can_monitor_spa(request.user):
        messages.error(request, "Permission denied.")
        return redirect('home')
    scope = _scope_branch(request)
    orders = SpaOrder.objects.select_related('booking__room', 'booking__user')\
        .prefetch_related('items__service').order_by('-created_at')
    if scope:
        orders = orders.filter(booking__branch=scope)
    page_obj = paginate(request, orders)
    revenue = orders.filter(is_paid=True).aggregate(Sum('total_price'))['total_price__sum'] or 0
    return render(request, 'housekeeping_panel/spa_monitor.html', {
        'orders': page_obj, 'page_obj': page_obj,
        'revenue': _money(revenue), 'base_template': _panel_base(request),
    })


@login_required
def update_spa_status(request, order_id, status):
    if not _can_monitor_spa(request.user):
        return redirect('home')
    order = get_object_or_404(SpaOrder, id=order_id)
    if status in dict(SpaOrder.STATUS_CHOICES):
        order.status = status
        if hasattr(request.user, 'employee_profile'):
            order.handled_by = request.user.employee_profile
        order.save()
        log_action(request, action='status', module='SpaOrder',
                   summary=f"Spa order #{order.id} -> {order.get_status_display()}",
                   object=order, branch=order.branch)
        messages.success(request, f"Spa order #{order.id} marked as {order.get_status_display()}.")
    return redirect('spa_monitor')


@login_required
def mark_spa_paid(request, order_id):
    if not _can_monitor_spa(request.user):
        return redirect('home')
    order = get_object_or_404(SpaOrder, id=order_id)
    order.is_paid = True
    if hasattr(request.user, 'employee_profile'):
        order.handled_by = request.user.employee_profile
    order.save()
    log_action(request, action='payment', module='SpaOrder',
               summary=f"Spa order #{order.id} marked paid", object=order, branch=order.branch)
    messages.success(request, f"Spa order #{order.id} marked as paid.")
    return redirect('spa_monitor')


# ---- Spa service menu management (Admin / Manager) ----
@login_required
def spa_services(request):
    if not _can_manage_wallet(request.user):
        return redirect('home')
    active = _scope_branch(request)
    services = SpaService.objects.all()
    if active:
        services = _branch_menu_filter(services, active)
    page_obj = paginate(request, services)
    return render(request, 'admin_panel/spa_services.html', {
        'services': page_obj, 'page_obj': page_obj, 'base_template': _panel_base(request),
    })


@login_required
def add_spa_service(request):
    if not _can_manage_wallet(request.user):
        return redirect('home')
    active = _active_branch(request)
    if request.method == 'POST':
        form = SpaServiceForm(request.POST, request.FILES)
        if form.is_valid():
            svc = form.save(commit=False)
            if not svc.branch_id:
                svc.branch = active or _default_branch()
            svc.save()
            log_action(request, action='create', module='SpaService',
                       summary=f"Created spa service {svc.name}", object=svc, branch=svc.branch)
            messages.success(request, f"Spa service '{svc.name}' added.")
            return redirect('spa_services')
    else:
        form = SpaServiceForm(initial={'branch': active} if active else None)
    return render(request, 'admin_panel/spa_service_form.html', {
        'form': form, 'title': 'Add Spa Service', 'base_template': _panel_base(request),
    })


@login_required
def edit_spa_service(request, service_id):
    if not _can_manage_wallet(request.user):
        return redirect('home')
    svc = get_object_or_404(SpaService, id=service_id)
    if request.method == 'POST':
        form = SpaServiceForm(request.POST, request.FILES, instance=svc)
        if form.is_valid():
            form.save()
            log_action(request, action='update', module='SpaService',
                       summary=f"Updated spa service {svc.name}", object=svc, branch=svc.branch)
            messages.success(request, f"{svc.name} updated.")
            return redirect('spa_services')
    else:
        form = SpaServiceForm(instance=svc)
    return render(request, 'admin_panel/spa_service_form.html', {
        'form': form, 'title': 'Edit Spa Service', 'base_template': _panel_base(request),
    })


@login_required
def delete_spa_service(request, service_id):
    if not _can_manage_wallet(request.user):
        return redirect('home')
    svc = get_object_or_404(SpaService, id=service_id)
    name = svc.name
    log_action(request, action='delete', module='SpaService',
               summary=f"Deleted spa service {name}", object=svc, branch=svc.branch)
    svc.delete()
    messages.success(request, f"{name} removed.")
    return redirect('spa_services')


# ===========================================================================
# AUDIT LOG (Admin + Manager only)
# ===========================================================================
@login_required
def audit_log_view(request):
    if not _can_view_audit(request.user):
        messages.error(request, "Only Admin and Manager can view audit logs.")
        return redirect('home')

    scope = _scope_branch(request)
    qs = AuditLog.objects.select_related('user', 'branch').all()
    if scope is not None:
        qs = qs.filter(Q(branch=scope) | Q(branch__isnull=True))

    sel_q = (request.GET.get('q') or '').strip()
    sel_user = (request.GET.get('user') or '').strip()
    sel_action = (request.GET.get('action') or '').strip()
    sel_module = (request.GET.get('module') or '').strip()
    sel_start = (request.GET.get('start') or '').strip()
    sel_end = (request.GET.get('end') or '').strip()

    if sel_q:
        qs = qs.filter(Q(summary__icontains=sel_q) | Q(object_repr__icontains=sel_q))
    if sel_user.isdigit():
        qs = qs.filter(user_id=int(sel_user))
    if sel_action in dict(AuditLog.ACTION_CHOICES):
        qs = qs.filter(action=sel_action)
    if sel_module:
        qs = qs.filter(module__iexact=sel_module)
    start_d = _parse_iso_date(sel_start)
    end_d = _parse_iso_date(sel_end)
    if start_d:
        qs = qs.filter(created_at__date__gte=start_d)
    if end_d:
        qs = qs.filter(created_at__date__lte=end_d)

    page_obj = paginate(request, qs, per_page=25)

    staff_users = CustomUser.objects.filter(role__in=['admin', 'employee'], is_active=True)\
        .order_by('first_name', 'username')
    modules = list(AuditLog.objects.order_by().values_list('module', flat=True).distinct()[:50])

    return render(request, 'admin_panel/audit_log.html', {
        'logs': page_obj, 'page_obj': page_obj,
        'staff_users': staff_users,
        'action_choices': AuditLog.ACTION_CHOICES,
        'modules': modules,
        'sel_q': sel_q, 'sel_user': sel_user, 'sel_action': sel_action,
        'sel_module': sel_module, 'sel_start': sel_start, 'sel_end': sel_end,
        'base_template': _panel_base(request),
    })