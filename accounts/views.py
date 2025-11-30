import json
from django.utils import timezone 
from django.shortcuts import get_object_or_404, render, redirect
from django.contrib.auth import login
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.decorators import login_required
from django.contrib.auth.hashers import make_password 
from accounts.models import Booking, CleaningLog, CustomUser, Customer, Employee, FoodItem, FoodOrder, Room
from .forms import BookingForm, CustomerEditForm, CustomerSignUpForm, EmployeeCreationForm, EmployeeEditForm, FoodItemForm, RoomForm, WalkInBookingForm
from django.contrib import messages
from django.db.models.functions import TruncMonth, TruncDay 
from .decorators import admin_required, customer_required, employee_required
from datetime import timedelta, date
# --- COMMON VIEWS ---


def index(request):
    # Fetch top 3 available rooms for the homepage
    featured_rooms = Room.objects.filter(room_status='available')[:3]
    return render(request, 'common/home.html', {'featured_rooms': featured_rooms})

def room_list(request):
    # View for "All Rooms" page
    rooms = Room.objects.filter(room_status='available')
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
    
    # 1. Safety Check: Is it actually available?
    if room.room_status != 'available':
        messages.error(request, "Sorry, this room is currently unavailable.")
        return redirect('room_list')

    if request.method == 'POST':
        form = BookingForm(request.POST)
        if form.is_valid():
            # 2. Create the Booking Record
            booking = form.save(commit=False)
            booking.user = request.user
            booking.room = room
            booking.save()
            
            # 3. LOCK THE ROOM (Make it unavailable for others)
            room.room_status = 'occupied' 
            room.save()
            
            messages.success(request, f"Success! You have booked Room {room.room_number}. It is now reserved for you.")
            return redirect('customer_dashboard')
    else:
        form = BookingForm()
    
    return render(request, 'customer_panel/booking_form.html', {'room': room, 'form': form})



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
    # 1. KPI CARDS DATA
    total_revenue = Booking.objects.filter(is_paid=True).aggregate(Sum('total_amount'))['total_amount__sum'] or 0
    total_bookings = Booking.objects.count()
    active_guests = Booking.objects.filter(actual_check_in__isnull=False, actual_check_out__isnull=True).count()
    
    # Calculate Occupancy Rate
    total_rooms = Room.objects.count()
    occupancy_rate = 0
    if total_rooms > 0:
        occupied_rooms = Room.objects.filter(room_status='occupied').count()
        occupancy_rate = int((occupied_rooms / total_rooms) * 100)

    # 2. CHART DATA: Revenue Trend (Last 7 Days)
    # Using Daily data is much easier to generate for demos than Monthly
    last_7_days = timezone.now() - timedelta(days=7)
    daily_data = Booking.objects.filter(is_paid=True, created_at__gte=last_7_days)\
        .annotate(day=TruncDay('created_at'))\
        .values('day')\
        .annotate(revenue=Sum('total_amount'))\
        .order_by('day')
    
    # Process Data
    chart_months = []
    chart_revenue = []
    
    # for entry in daily_data:
    #     chart_months.append(entry['day'].strftime('%a')) # Mon, Tue, Wed...
    #     chart_revenue.append(float(entry['revenue']))

    # --- DEMO MODE (FOR THUMBNAILS/EMPTY STATES) ---
    # If the database has no revenue data, we inject fake data so the chart looks good.
    if not chart_revenue:
        chart_months = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
        # Generate a nice looking curve
        chart_revenue = [120, 190, 150, 250, 210, 320, 280] 

    # 3. CHART DATA: Room Type Popularity
    room_stats = Booking.objects.values('room__room_type')\
        .annotate(count=Count('id'))\
        .order_by('-count')
    
    room_labels = [item['room__room_type'].replace('_', ' ').title() for item in room_stats]
    room_counts = [item['count'] for item in room_stats]
    
    # Demo Mode for Room Chart
    if not room_counts:
        room_labels = ['Single Room', 'Double Room', 'Suite', 'Deluxe']
        room_counts = [15, 25, 10, 5]

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
    }
    return render(request, 'admin_panel/dashboard.html', context)

@login_required
@admin_required
def add_employee(request):
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
        form = EmployeeCreationForm()
    
    return render(request, 'admin_panel/add_employee.html', {'form': form})


@login_required
@admin_required
def view_employees(request):
    # Fetch all users who have an employee profile
    employees = Employee.objects.select_related('user').all().order_by('-id')
    return render(request, 'admin_panel/view_employees.html', {'employees': employees})

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
    rooms = Room.objects.all().order_by('room_number')
    return render(request, 'admin_panel/view_rooms.html', {'rooms': rooms})

@login_required
@admin_required
def add_room(request):
    if request.method == 'POST':
        form = RoomForm(request.POST, request.FILES)
        if form.is_valid():
            form.save()
            messages.success(request, "New room added successfully!")
            return redirect('view_rooms')
    else:
        form = RoomForm()
    return render(request, 'admin_panel/add_room.html', {'form': form, 'title': 'Add New Room'})

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



@login_required
@admin_required
def view_guests(request):
    guests = Customer.objects.select_related('user').all().order_by('-id')
    return render(request, 'admin_panel/view_guests.html', {'guests': guests})

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
    return render(request, 'customer_panel/my_bookings.html', {'bookings': all_bookings})
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
@employee_required(allowed_jobs=['receptionist',  'admin']) 
# Note: Admins pass this check if you add 'admin' to role logic or separate decorators
def view_bookings(request):
    # Show active bookings (not yet checked out) first
    bookings = Booking.objects.select_related('user', 'room').order_by('-id')
    # RENDER DIFFERENT TEMPLATE BASED ON ROLE
    if request.user.role == 'receptionist' or (request.user.role == 'employee' and request.user.employee_profile.job_type == 'receptionist'):
        return render(request, 'receptionist_panel/booking_history.html', {'bookings': bookings})
        
    return render(request, 'admin_panel/view_bookings.html', {'bookings': bookings})

@login_required
def staff_check_in(request, booking_id):
    if request.user.role not in ['admin', 'employee']:
        return redirect('home')
        
    booking = get_object_or_404(Booking, id=booking_id)
    
    if not booking.actual_check_in:
        booking.actual_check_in = timezone.now()
        booking.save()
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
    return render(request, 'admin_panel/view_cleaning_logs.html', {'logs': logs})
@login_required
@employee_required(allowed_jobs=['housekeeping'])
def housekeeping_history(request):
    # Fetch ALL history for this employee
    my_history = CleaningLog.objects.filter(employee=request.user.employee_profile).order_by('-cleaned_at')
    return render(request, 'housekeeping_panel/history.html', {'logs': my_history})

@login_required
@employee_required(allowed_jobs=['housekeeping'])
def housekeeping_profile(request):
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

    if request.method == 'POST':
        selected_item_ids = request.POST.getlist('items')
        if not selected_item_ids:
            messages.error(request, "Please select at least one item.")
            return redirect('order_food')
            
        # Create Order
        order = FoodOrder.objects.create(booking=active_booking)
        total = 0
        for item_id in selected_item_ids:
            item = FoodItem.objects.get(id=item_id)
            order.items.add(item)
            total += item.price
        
        order.total_price = total
        order.save()
        
        messages.success(request, "Order placed successfully! The kitchen is preparing your food.")
        return redirect('customer_food_history')

    return render(request, 'customer_panel/order_food.html', {
        'menu': menu_items,
        'room': active_booking.room
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
    return render(request, 'kitchen_panel/history.html', {'orders': delivered_orders})


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
        
    return render(request, 'admin_panel/kitchen_history.html', {
        'orders': delivered_orders,
        'stats': chef_stats
    })
@login_required
@admin_required
def view_food_menu(request):
    food_items = FoodItem.objects.all().order_by('category', 'name')
    return render(request, 'admin_panel/view_food_menu.html', {'food_items': food_items})

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
    return render(request, 'customer_panel/food_history.html', {'orders': orders})
@login_required
@admin_required
def admin_kitchen_monitor(request):
    # NEW: Admin version of the KDS
    active_orders = FoodOrder.objects.exclude(status='delivered').order_by('created_at')
    return render(request, 'admin_panel/kitchen_monitor.html', {'orders': active_orders})


@login_required
@employee_required(allowed_jobs=['kitchen'])
def kitchen_profile(request):
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
    # List all customers
    guests = Customer.objects.select_related('user').all().order_by('-id')
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
    grand_total = room_total + food_total
    
    context = {
        'booking': booking,
        'duration': duration,
        'room_total': room_total,
        'food_orders': food_orders,
        'food_total': food_total,
        'grand_total': grand_total
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