import json
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
)
from .forms import (
    BookingForm, CustomerEditForm, CustomerSignUpForm, EmployeeCreationForm, EmployeeEditForm,
    FoodItemForm, RoomForm, WalkInBookingForm, PaymentSettingForm, PaymentReceiptForm,
    DrinkForm, RestockForm, BranchForm, MessageForm, SiteSettingForm, ExpenseForm, WalletCreditForm,
)
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
    return render(request, 'common/home.html', {'featured_rooms': featured_rooms})

def room_list(request):
    # All bookable rooms stay visible even if reserved for some dates (only hide maintenance).
    rooms = _annotate_room_availability(Room.objects.exclude(room_status='maintenance').order_by('room_number'))
    # Logged-in guests keep their dashboard sidebar while browsing rooms.
    if request.user.is_authenticated and request.user.role == 'customer':
        return render(request, 'customer_panel/browse_rooms.html', {'rooms': rooms})
    return render(request, 'common/rooms.html', {'rooms': rooms})

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
    return render(request, 'common/about.html')

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
    bookings_qs = Booking.objects.all()
    rooms_qs = Room.objects.all()
    if active:
        bookings_qs = bookings_qs.filter(branch=active)
        rooms_qs = rooms_qs.filter(branch=active)

    # 1. KPI CARDS DATA
    total_revenue = bookings_qs.filter(is_paid=True).aggregate(Sum('total_amount'))['total_amount__sum'] or 0
    total_bookings = bookings_qs.count()
    active_guests = bookings_qs.filter(actual_check_in__isnull=False, actual_check_out__isnull=True).count()
    
    # Calculate Occupancy Rate
    total_rooms = rooms_qs.count()
    occupancy_rate = 0
    if total_rooms > 0:
        occupied_rooms = rooms_qs.filter(room_status='occupied').count()
        occupancy_rate = int((occupied_rooms / total_rooms) * 100)

    # 2. CHART DATA: Revenue Trend (Last 7 Days)
    # Using Daily data is much easier to generate for demos than Monthly
    last_7_days = timezone.now() - timedelta(days=7)
    daily_data = bookings_qs.filter(is_paid=True, created_at__gte=last_7_days)\
        .annotate(day=TruncDay('created_at'))\
        .values('day')\
        .annotate(revenue=Sum('total_amount'))\
        .order_by('day')
    
    # Process Data
    chart_months = []
    chart_revenue = []
    
    for entry in daily_data:
        chart_months.append(entry['day'].strftime('%a')) # Mon, Tue, Wed...
        chart_revenue.append(float(entry['revenue']))

    # --- DEMO MODE (FOR THUMBNAILS/EMPTY STATES) ---
    # if not chart_revenue:
    #     chart_months = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
    #     # Generate a nice looking curve
    #     chart_revenue = [120, 190, 150, 250, 210, 320, 280] 

    # 3. CHART DATA: Room Type Popularity
    room_stats = bookings_qs.values('room__room_type')\
        .annotate(count=Count('id'))\
        .order_by('-count')
    
    room_labels = [item['room__room_type'].replace('_', ' ').title() for item in room_stats]
    room_counts = [item['count'] for item in room_stats]
    
    # Demo Mode for Room Chart
    # if total_bookings < 11:
    #     room_labels = ['Single Room', 'Double Room', 'Executive Suite', 'Deluxe King', 'Family Studio']
    #     room_counts = [45, 32, 15, 28, 12] # Values that make a nice donut chart


    context = {
        'total_revenue': total_revenue,
        'total_bookings': total_bookings,
        'active_guests': active_guests,
        'occupancy_rate': occupancy_rate,
        # JSON dumps for JS
        'chart_months': json.dumps(chart_months),
        'chart_revenue': json.dumps(chart_revenue),
        'chart_room_labels': json.dumps(room_labels),
        'chart_room_counts': json.dumps(room_counts),
        'active_branch': active,
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
            # New rooms belong to the branch currently being managed.
            if active and not room.branch_id:
                room.branch = active
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
    
    return render(request, 'admin_panel/edit_guest.html', {'form': form, 'guest': guest})

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
    
    in_house = Booking.objects.filter(
        actual_check_in__isnull=False,
        actual_check_out__isnull=True
    ).count()

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
    bookings = Booking.objects.select_related('user', 'room').order_by('-id')
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

    menu_items = FoodItem.objects.filter(is_available=True)
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
    active_orders = FoodOrder.objects.exclude(status='delivered').order_by('created_at')
    return render(request, 'kitchen_panel/dashboard.html', {'orders': active_orders})

@login_required
@employee_required(allowed_jobs=['kitchen', 'manager', 'admin'])
def kitchen_history(request):
    # Fetch only DELIVERED orders
    delivered_orders = FoodOrder.objects.filter(status='delivered').order_by('-created_at')
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
    
    # Smart Redirect
    referer = request.META.get('HTTP_REFERER')
    if referer and 'admin' in referer:
         return redirect('admin_kitchen_monitor')
    return redirect('kitchen_dashboard')


from django.db.models import Count
@login_required
@admin_required
def admin_kitchen_history(request):
    # 1. Detailed Log: All delivered orders
    delivered_orders = FoodOrder.objects.filter(status='delivered').select_related('booking__room', 'chef__user').order_by('-created_at')
    
    # 2. Leaderboard: Count orders per staff member
    chef_stats = FoodOrder.objects.filter(status='delivered')\
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
    food_items = FoodItem.objects.all().order_by('category', 'name')
    page_obj = paginate(request, food_items)
    return render(request, 'admin_panel/view_food_menu.html', {'food_items': page_obj, 'page_obj': page_obj})

@login_required
@admin_required
def add_food_item(request):
    if request.method == 'POST':
        form = FoodItemForm(request.POST, request.FILES)
        if form.is_valid():
            form.save()
            messages.success(request, "New food item added to the menu!")
            return redirect('view_food_menu')
    else:
        form = FoodItemForm()
    return render(request, 'admin_panel/add_food_item.html', {'form': form, 'title': 'Add Menu Item'})

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
    active_orders = FoodOrder.objects.exclude(status='delivered').order_by('created_at')
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
        }.get(job, 'admin_panel/adminbase.html')
    return 'admin_panel/adminbase.html'


# ===========================================================================
# HOTEL CREDIT WALLET + BOOKING CANCELLATION
# ===========================================================================
@login_required
@customer_required
def customer_wallet(request):
    wallet = _get_wallet(request.user)
    transactions = wallet.transactions.all()
    return render(request, 'customer_panel/wallet.html', {'wallet': wallet, 'transactions': transactions})


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

    return redirect('customer_bookings')


# ===========================================================================
# ADMIN: SITE SETTINGS (Currency + VAT)
# ===========================================================================
@login_required
@admin_required
def site_settings(request):
    settings_obj = SiteSetting.load()
    if request.method == 'POST':
        form = SiteSettingForm(request.POST, instance=settings_obj)
        if form.is_valid():
            form.save()
            messages.success(request, "Site settings (currency / VAT) updated successfully!")
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

    drinks = Drink.objects.filter(is_available=True, stock_quantity__gt=0)
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
    active_orders = BarOrder.objects.exclude(status='served').prefetch_related('items__drink')
    low_stock = Drink.objects.filter(stock_quantity__lte=5).order_by('stock_quantity')[:5]
    return render(request, 'bar_panel/dashboard.html', {'orders': active_orders, 'low_stock': low_stock})


@login_required
@employee_required(allowed_jobs=['bar'])
def update_bar_order_status(request, order_id, status):
    order = get_object_or_404(BarOrder, id=order_id)
    order.status = status
    if status == 'served' and request.user.role == 'employee' and hasattr(request.user, 'employee_profile'):
        order.bar_staff = request.user.employee_profile
    order.save()
    return redirect('bar_dashboard')


@login_required
@employee_required(allowed_jobs=['bar'])
def bar_history(request):
    orders = BarOrder.objects.filter(status='served').prefetch_related('items__drink').order_by('-created_at')
    page_obj = paginate(request, orders)
    return render(request, 'bar_panel/history.html', {'orders': page_obj, 'page_obj': page_obj})


@login_required
@employee_required(allowed_jobs=['bar', 'manager'])
def bar_inventory(request):
    drinks = Drink.objects.all().order_by('name')
    page_obj = paginate(request, drinks)
    return render(request, 'bar_panel/inventory.html', {'drinks': page_obj, 'page_obj': page_obj, 'base_template': _panel_base(request)})


@login_required
@employee_required(allowed_jobs=['bar', 'manager'])
def add_drink(request):
    if request.method == 'POST':
        form = DrinkForm(request.POST, request.FILES)
        if form.is_valid():
            form.save()
            messages.success(request, "New drink added to the bar menu!")
            return redirect('bar_inventory')
    else:
        form = DrinkForm()
    return render(request, 'bar_panel/drink_form.html', {'form': form, 'title': 'Add Drink', 'base_template': _panel_base(request)})


@login_required
@employee_required(allowed_jobs=['bar', 'manager'])
def edit_drink(request, drink_id):
    drink = get_object_or_404(Drink, id=drink_id)
    if request.method == 'POST':
        form = DrinkForm(request.POST, request.FILES, instance=drink)
        if form.is_valid():
            form.save()
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
    food_orders = FoodOrder.objects.select_related('booking__room', 'booking__user').order_by('-created_at')
    bar_orders = BarOrder.objects.select_related('booking__room', 'booking__user').prefetch_related('items__drink').order_by('-created_at')

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

            count = 0
            for user in recipients:
                Message.objects.create(
                    sender=request.user,
                    recipient=user,
                    recipient_role=recipient_role,
                    subject=subject,
                    body=body,
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
        form = BranchForm(request.POST)
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
        form = BranchForm(request.POST, instance=branch)
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
        messages.success(request, f"Switched to {branch.name}. The dashboard, rooms and staff now show this branch.")

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
def _period_range(period):
    """Return (start_date, end_date, label) for day/week/month/year."""
    today = timezone.now().date()
    if period == 'day':
        return today, today, "Today"
    if period == 'week':
        return today - timedelta(days=6), today, "This Week (last 7 days)"
    if period == 'year':
        return date(today.year, 1, 1), today, f"This Year ({today.year})"
    # default: month (current calendar month)
    return today.replace(day=1), today, today.strftime("This Month (%B %Y)")


@login_required
def accounting_report(request):
    if not _can_manage_wallet(request.user):
        messages.error(request, "Only Admins and Managers can view the accounting report.")
        return redirect('home')

    period = request.GET.get('period', 'month')
    if period not in ('day', 'week', 'month', 'year'):
        period = 'month'
    start, end, label = _period_range(period)

    active = _active_branch(request)

    bookings = Booking.objects.filter(is_paid=True, created_at__date__gte=start, created_at__date__lte=end)
    food = FoodOrder.objects.filter(is_paid=True, created_at__date__gte=start, created_at__date__lte=end)
    bar = BarOrder.objects.filter(is_paid=True, created_at__date__gte=start, created_at__date__lte=end)
    expenses = Expense.objects.filter(spent_on__gte=start, spent_on__lte=end)

    if active:
        bookings = bookings.filter(branch=active)
        food = food.filter(booking__branch=active)
        bar = bar.filter(booking__branch=active)
        expenses = expenses.filter(branch=active)

    bookings_total = bookings.aggregate(Sum('total_amount'))['total_amount__sum'] or Decimal('0')
    food_total = food.aggregate(Sum('total_price'))['total_price__sum'] or Decimal('0')
    bar_total = bar.aggregate(Sum('total_price'))['total_price__sum'] or Decimal('0')

    # Bar gross profit (sale price - cost price) for served/paid items.
    bar_profit = Decimal('0')
    bar_items = BarOrderItem.objects.filter(order__in=bar).select_related('drink')
    for item in bar_items:
        cost = item.drink.cost_price if item.drink else Decimal('0')
        bar_profit += (item.price - (cost or Decimal('0'))) * item.quantity

    expenses_total = expenses.aggregate(Sum('amount'))['amount__sum'] or Decimal('0')

    combined_revenue = bookings_total + food_total + bar_total
    net = combined_revenue - expenses_total

    # Expense breakdown by category
    category_breakdown = expenses.values('category').annotate(total=Sum('amount')).order_by('-total')
    cat_labels = dict(Expense.CATEGORY_CHOICES)
    category_breakdown = [
        {'label': cat_labels.get(c['category'], c['category']), 'total': c['total']}
        for c in category_breakdown
    ]

    context = {
        'period': period,
        'period_label': label,
        'start': start,
        'end': end,
        'bookings_total': _money(bookings_total),
        'food_total': _money(food_total),
        'bar_total': _money(bar_total),
        'bar_profit': _money(bar_profit),
        'combined_revenue': _money(combined_revenue),
        'expenses_total': _money(expenses_total),
        'net': _money(net),
        'is_profit': net >= 0,
        'net_abs': _money(abs(net)),
        'category_breakdown': category_breakdown,
        'active_branch': active,
        'base_template': _panel_base(request),
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