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

    branch = models.ForeignKey('Branch', on_delete=models.SET_NULL, null=True, blank=True, related_name='rooms')

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
    BAR = 'bar'
    MANAGER = 'manager'

    JOB_CHOICES = [
        (RECEPTIONIST, 'Receptionist'),
        (KITCHEN, 'Kitchen Staff'),
        (HOUSEKEEPING, 'Housekeeping'),
        (BAR, 'Bar Staff'),
        (MANAGER, 'Manager'),
    ]
    
    job_type = models.CharField(max_length=20, choices=JOB_CHOICES)
    
    # Shared Fields
    salary = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    id_card_number = models.CharField(max_length=20, unique=True)
    years_of_experience = models.PositiveIntegerField(default=0)

    branch = models.ForeignKey('Branch', on_delete=models.SET_NULL, null=True, blank=True, related_name='staff')

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

    # Cancellation / refund
    is_cancelled = models.BooleanField(default=False)
    cancelled_at = models.DateTimeField(blank=True, null=True)

    branch = models.ForeignKey('Branch', on_delete=models.SET_NULL, null=True, blank=True, related_name='bookings')

    created_at = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return f"{self.user.username} - {self.room.room_number}"

    @property
    def status(self):
        if self.is_cancelled:
            return "Cancelled"
        if self.actual_check_out:
            return "Checked Out"
        elif self.actual_check_in:
            return "Checked In"
        return "Booked"

    @property
    def payment_status(self):
        """Human-friendly payment state for the booking."""
        if self.is_paid:
            return "Paid"
        # Any uploaded-but-not-confirmed receipt => awaiting receptionist confirmation
        if self.receipts.filter(status=PaymentReceipt.STATUS_PENDING).exists():
            return "Payment Confirmation Pending"
        if self.receipts.filter(status=PaymentReceipt.STATUS_REJECTED).exists():
            return "Payment Rejected"
        return "Unpaid"
    

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
    is_paid = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    chef = models.ForeignKey(Employee, on_delete=models.SET_NULL, null=True, blank=True, related_name='food_orders')
    
    
    def __str__(self):
        return f"Order #{self.id} - Room {self.booking.room.room_number}"


class PaymentSetting(models.Model):
    """
    Singleton model holding the hotel's bank transfer details.
    The Admin can edit these from the dashboard so guests always
    see the latest account information when paying online.
    """
    bank_name = models.CharField(max_length=100, default="Global Trust Bank")
    account_holder_name = models.CharField(max_length=100, default="Grand Hotel Pvt Ltd")
    account_number = models.CharField(max_length=40, default="1029384756")
    ifsc_code = models.CharField(max_length=20, blank=True, default="GTBL0001234")
    branch = models.CharField(max_length=100, blank=True, default="Main Branch")
    payment_link = models.URLField(blank=True, null=True, help_text="Optional online payment link.")
    instructions = models.TextField(
        blank=True,
        default="Please transfer the total booking amount to the account above and upload your payment receipt."
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Payment Setting"
        verbose_name_plural = "Payment Settings"

    def __str__(self):
        return f"Payment Details - {self.bank_name}"

    def save(self, *args, **kwargs):
        # Force a single row so there is always exactly one settings record.
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class PaymentReceipt(models.Model):
    STATUS_PENDING = 'pending'
    STATUS_CONFIRMED = 'confirmed'
    STATUS_REJECTED = 'rejected'

    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending Confirmation'),
        (STATUS_CONFIRMED, 'Confirmed'),
        (STATUS_REJECTED, 'Rejected'),
    ]

    booking = models.ForeignKey(Booking, on_delete=models.CASCADE, related_name='receipts')
    receipt_file = models.FileField(upload_to='payment_receipts/')
    amount = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    note = models.CharField(max_length=255, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    uploaded_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-uploaded_at']

    def __str__(self):
        return f"Receipt for Booking #{self.booking.id} ({self.get_status_display()})"


# ---------------------------------------------------------------------------
# MULTI-BRANCH / LOCATION MANAGEMENT
# ---------------------------------------------------------------------------
class Branch(models.Model):
    name = models.CharField(max_length=100)
    code = models.CharField(max_length=20, unique=True)
    address = models.TextField(blank=True)
    city = models.CharField(max_length=100, blank=True)
    phone = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name_plural = "Branches"
        ordering = ['name']

    def __str__(self):
        return f"{self.name} ({self.code})"


# ---------------------------------------------------------------------------
# HOTEL CREDIT WALLET (Refunds on cancellation)
# ---------------------------------------------------------------------------
class Wallet(models.Model):
    user = models.OneToOneField(CustomUser, on_delete=models.CASCADE, related_name='wallet')
    balance = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)

    def __str__(self):
        return f"{self.user.username}'s Wallet: {self.balance}"

    def credit(self, amount, reason=""):
        self.balance += amount
        self.save()
        WalletTransaction.objects.create(wallet=self, amount=amount, txn_type=WalletTransaction.CREDIT, reason=reason)

    def debit(self, amount, reason=""):
        self.balance -= amount
        self.save()
        WalletTransaction.objects.create(wallet=self, amount=amount, txn_type=WalletTransaction.DEBIT, reason=reason)


class WalletTransaction(models.Model):
    CREDIT = 'credit'
    DEBIT = 'debit'
    TYPE_CHOICES = [(CREDIT, 'Credit'), (DEBIT, 'Debit')]

    wallet = models.ForeignKey(Wallet, on_delete=models.CASCADE, related_name='transactions')
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    txn_type = models.CharField(max_length=10, choices=TYPE_CHOICES)
    reason = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.get_txn_type_display()} {self.amount} - {self.wallet.user.username}"


# ---------------------------------------------------------------------------
# BAR SECTION (Drinks, Orders, Inventory)
# ---------------------------------------------------------------------------
class Drink(models.Model):
    CATEGORY_CHOICES = [
        ('soft', 'Soft Drink'),
        ('juice', 'Juice'),
        ('beer', 'Beer'),
        ('wine', 'Wine'),
        ('spirit', 'Spirit'),
        ('cocktail', 'Cocktail'),
        ('hot', 'Hot Beverage'),
    ]
    name = models.CharField(max_length=100)
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES)
    price = models.DecimalField(max_digits=8, decimal_places=2)
    image = models.ImageField(upload_to='drink_images/', blank=True, null=True)
    stock_quantity = models.PositiveIntegerField(default=0)
    is_available = models.BooleanField(default=True)
    branch = models.ForeignKey('Branch', on_delete=models.SET_NULL, null=True, blank=True, related_name='drinks')

    def __str__(self):
        return f"{self.name} (Stock: {self.stock_quantity})"

    @property
    def in_stock(self):
        return self.stock_quantity > 0


class BarOrder(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('preparing', 'Preparing'),
        ('served', 'Served'),
    ]
    booking = models.ForeignKey(Booking, on_delete=models.CASCADE, related_name='bar_orders')
    total_price = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    is_paid = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    bar_staff = models.ForeignKey(Employee, on_delete=models.SET_NULL, null=True, blank=True, related_name='bar_orders')

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Bar Order #{self.id} - Room {self.booking.room.room_number}"


class BarOrderItem(models.Model):
    order = models.ForeignKey(BarOrder, on_delete=models.CASCADE, related_name='items')
    drink = models.ForeignKey(Drink, on_delete=models.CASCADE)
    quantity = models.PositiveIntegerField(default=1)
    price = models.DecimalField(max_digits=8, decimal_places=2, default=0.00)

    def __str__(self):
        return f"{self.quantity} x {self.drink.name}"

    @property
    def subtotal(self):
        return self.quantity * self.price


class StockTransaction(models.Model):
    """Inventory log for restocking/adjusting drink stock (accounting)."""
    drink = models.ForeignKey(Drink, on_delete=models.CASCADE, related_name='stock_transactions')
    quantity = models.IntegerField(help_text="Positive for restock, negative for sale/adjustment")
    note = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.drink.name}: {self.quantity:+d}"


# ---------------------------------------------------------------------------
# IN-APP MESSAGING
# ---------------------------------------------------------------------------
class Message(models.Model):
    DEPARTMENT_CHOICES = [
        ('receptionist', 'Reception'),
        ('kitchen', 'Kitchen'),
        ('bar', 'Bar'),
        ('housekeeping', 'Housekeeping'),
        ('manager', 'Manager'),
        ('admin', 'Admin / Front Office'),
    ]

    sender = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='sent_messages')
    recipient = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='received_messages')
    # The department this message was addressed to (blank for a direct reply to a guest)
    recipient_role = models.CharField(max_length=20, choices=DEPARTMENT_CHOICES, blank=True)
    subject = models.CharField(max_length=150, blank=True)
    body = models.TextField()
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"From {self.sender} to {self.recipient}"

    @property
    def target_label(self):
        if self.recipient_role:
            return self.get_recipient_role_display()
        return self.recipient.get_full_name() or self.recipient.username


# ---------------------------------------------------------------------------
# SITE CONFIGURATION (Currency + VAT)
# ---------------------------------------------------------------------------
class SiteSetting(models.Model):
    hotel_name = models.CharField(max_length=100, default="Grand Hotel")
    currency_symbol = models.CharField(max_length=5, default="$")
    currency_code = models.CharField(max_length=5, default="USD")
    vat_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=0.00,
                                          help_text="VAT % applied to rooms and products.")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Site Setting"
        verbose_name_plural = "Site Settings"

    def __str__(self):
        return f"Site Settings ({self.currency_code}, VAT {self.vat_percentage}%)"

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj