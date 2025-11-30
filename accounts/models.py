from django.db import models
from django.contrib.auth.models import AbstractUser, UserManager

class CustomUserManager(UserManager):
    def create_superuser(self, username, email=None, password=None, **extra_fields):
        extra_fields.setdefault('role', 'admin')
        if extra_fields.get('role') != 'admin':
            raise ValueError('Superuser must have role=admin.')
        return super().create_superuser(username, email, password, **extra_fields)

class CustomUser(AbstractUser):
    ADMIN = 'admin'
    EMPLOYEE = 'employee'  # Unified role for all staff
    CUSTOMER = 'customer'

    ROLE_CHOICES = [
        (ADMIN, 'Admin'),
        (EMPLOYEE, 'Employee'),
        (CUSTOMER, 'Customer'),
    ]

    role = models.CharField(max_length=15, choices=ROLE_CHOICES)
    mobile = models.CharField(max_length=15, blank=True, null=True)
    profile_picture = models.ImageField(upload_to='profile_pics/', blank=True, null=True)

    objects = CustomUserManager()

    def __str__(self):
        return f"{self.username} ({self.get_role_display()})"

class Room(models.Model):
    ROOM_TYPES = [
        ('single', 'Single Room'),
        ('double', 'Double Room'),
        ('suite', 'Suite'),
        ('deluxe', 'Deluxe Room'),
        ('family', 'Family Room'),
    ]
    
    # NEW STATUSES
    AVAILABLE = 'available'
    OCCUPIED = 'occupied'
    DIRTY = 'dirty'
    MAINTENANCE = 'maintenance'
    
    STATUS_CHOICES = [
        (AVAILABLE, 'Available'),
        (OCCUPIED, 'Occupied'),
        (DIRTY, 'Dirty'),
        (MAINTENANCE, 'Maintenance'),
    ]
    
    room_number = models.CharField(max_length=10, unique=True)
    room_type = models.CharField(max_length=20, choices=ROOM_TYPES)
    price_per_night = models.DecimalField(max_digits=10, decimal_places=2)
    capacity = models.PositiveIntegerField(help_text="Number of people")
    description = models.TextField(blank=True)
    room_image = models.ImageField(upload_to='room_images/', blank=True, null=True)
    
    # REPLACED is_available with room_status
    room_status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=AVAILABLE)
    
    def __str__(self):
        return f"Room {self.room_number} - {self.get_room_status_display()}"


class Employee(models.Model):
    """
    One profile for ALL staff members (Receptionist, Kitchen, etc.)
    We distinguish them by 'job_type'.
    """
    user = models.OneToOneField(CustomUser, on_delete=models.CASCADE, related_name='employee_profile')
    
    # Define Job Types
    RECEPTIONIST = 'receptionist'
    KITCHEN = 'kitchen'
    HOUSEKEEPING = 'housekeeping'
   
    
    JOB_CHOICES = [
        (RECEPTIONIST, 'Receptionist'),
        (KITCHEN, 'Kitchen Staff'),
        (HOUSEKEEPING, 'Housekeeping'),
        
    ]
    
    job_type = models.CharField(max_length=20, choices=JOB_CHOICES)
    
    # Shared Fields
    salary = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    id_card_number = models.CharField(max_length=20, unique=True)
    years_of_experience = models.PositiveIntegerField(default=0)
    
    def __str__(self):
        return f"{self.user.username} - {self.get_job_type_display()}"



class CleaningLog(models.Model):
    room = models.ForeignKey(Room, on_delete=models.CASCADE)
    employee = models.ForeignKey(Employee, on_delete=models.SET_NULL, null=True)
    cleaned_at = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return f"Room {self.room.room_number} cleaned by {self.employee.user.username} at {self.cleaned_at}"

class Customer(models.Model):
    user = models.OneToOneField(CustomUser, on_delete=models.CASCADE, related_name='customer_profile')
    address = models.TextField(blank=True, null=True)

    def __str__(self):
        return f"Customer: {self.user.username}"
    

class Booking(models.Model):
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE)
    room = models.ForeignKey('Room', on_delete=models.CASCADE)
    
    # Planned Dates (User selected)
    check_in = models.DateField()
    check_out = models.DateField()
    
    # Actual Operations (Staff actions)
    actual_check_in = models.DateTimeField(blank=True, null=True)
    actual_check_out = models.DateTimeField(blank=True, null=True)

    total_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    is_paid = models.BooleanField(default=False)
    payment_method = models.CharField(max_length=20, blank=True, null=True) # Cash, Card, UPI
    
    
    created_at = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return f"{self.user.username} - {self.room.room_number}"

    @property
    def status(self):
        if self.actual_check_out:
            return "Checked Out"
        elif self.actual_check_in:
            return "Checked In"
        return "Booked"
    

class FoodItem(models.Model):
    CATEGORY_CHOICES = [
        ('starter', 'Starter'),
        ('main_course', 'Main Course'),
        ('beverage', 'Beverage'),
        ('dessert', 'Dessert'),
    ]
    name = models.CharField(max_length=100)
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES)
    price = models.DecimalField(max_digits=6, decimal_places=2)
    image = models.ImageField(upload_to='food_images/', blank=True, null=True)
    is_available = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.name} (${self.price})"

class FoodOrder(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('cooking', 'Cooking'),
        ('ready', 'Ready to Serve'),
        ('delivered', 'Delivered'),
    ]
    
    booking = models.ForeignKey(Booking, on_delete=models.CASCADE) # Link to their room stay
    items = models.ManyToManyField(FoodItem) # Simple Many-to-Many for now
    total_price = models.DecimalField(max_digits=8, decimal_places=2, default=0.00)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    created_at = models.DateTimeField(auto_now_add=True)
    chef = models.ForeignKey(Employee, on_delete=models.SET_NULL, null=True, blank=True, related_name='food_orders')
    
    
    def __str__(self):
        return f"Order #{self.id} - Room {self.booking.room.room_number}"