from decimal import Decimal
from django.db import models
from django.contrib.auth.models import AbstractUser, UserManager
from django.utils import timezone

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
    SPA = 'spa'

    JOB_CHOICES = [
        (RECEPTIONIST, 'Receptionist'),
        (KITCHEN, 'Kitchen Staff'),
        (HOUSEKEEPING, 'Housekeeping'),
        (BAR, 'Bar Staff'),
        (MANAGER, 'Manager'),
        (SPA, 'Spa Therapist'),
    ]
    
    job_type = models.CharField(max_length=20, choices=JOB_CHOICES)
    
    # Shared Fields
    salary = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    id_card_number = models.CharField(max_length=20, unique=True)
    years_of_experience = models.PositiveIntegerField(default=0)

    branch = models.ForeignKey('Branch', on_delete=models.SET_NULL, null=True, blank=True, related_name='staff')

    # Managers can be granted access to multiple branches/locations by the admin.
    # The manager may then see and switch between ONLY these assigned branches.
    assigned_branches = models.ManyToManyField('Branch', blank=True, related_name='managers',
                                               help_text="Branches a manager is allowed to view and switch between.")

    def __str__(self):
        return f"{self.user.username} - {self.get_job_type_display()}"

    def allowed_branches(self):
        """Branches this manager may operate on (assigned, else their own branch)."""
        qs = self.assigned_branches.filter(is_active=True)
        if qs.exists():
            return qs
        if self.branch_id:
            return Branch.objects.filter(id=self.branch_id)
        return Branch.objects.none()



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
    branch = models.ForeignKey('Branch', on_delete=models.SET_NULL, null=True, blank=True, related_name='food_items')

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
    # Per-branch hotel identity (shown in the navbar, dashboard and invoices
    # when this branch is the active / current one).
    logo = models.ImageField(upload_to='branch_logos/', blank=True, null=True,
                             help_text="Logo shown in the navbar, dashboard and invoices for this branch.")
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
    # `price` is the SALE price shown to guests.
    price = models.DecimalField(max_digits=8, decimal_places=2)
    # `cost_price` is what the hotel paid (used only for profit calculations).
    cost_price = models.DecimalField(max_digits=8, decimal_places=2, default=0.00,
                                     help_text="Purchase/cost price used for profit calculation.")
    image = models.ImageField(upload_to='drink_images/', blank=True, null=True)
    stock_quantity = models.PositiveIntegerField(default=0)
    low_stock_threshold = models.PositiveIntegerField(default=5,
                                                      help_text="Alert when stock falls to or below this level.")
    expiry_date = models.DateField(null=True, blank=True,
                                   help_text="Used for product expiration alerts.")
    is_available = models.BooleanField(default=True)
    branch = models.ForeignKey('Branch', on_delete=models.SET_NULL, null=True, blank=True, related_name='drinks')

    def __str__(self):
        return f"{self.name} (Stock: {self.stock_quantity})"

    @property
    def in_stock(self):
        return self.stock_quantity > 0

    @property
    def is_low_stock(self):
        return self.stock_quantity <= (self.low_stock_threshold or 0)

    @property
    def is_expired(self):
        from django.utils import timezone
        return bool(self.expiry_date and self.expiry_date < timezone.now().date())

    @property
    def is_expiring_soon(self):
        from django.utils import timezone
        from datetime import timedelta
        if not self.expiry_date:
            return False
        today = timezone.now().date()
        return today <= self.expiry_date <= today + timedelta(days=7)

    @property
    def profit_per_unit(self):
        return (self.price or 0) - (self.cost_price or 0)


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
        ('guest', 'Guests'),
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
    hotel_logo = models.ImageField(upload_to='hotel/', blank=True, null=True,
                                   help_text="Logo shown on the website, dashboard and invoices.")
    hotel_address = models.TextField(blank=True, default="123 Luxury Ave, Hotel City")
    hotel_phone = models.CharField(max_length=30, blank=True, default="")
    hotel_email = models.EmailField(blank=True, default="contact@grandhotel.com")
    currency_symbol = models.CharField(max_length=5, default="$")
    currency_code = models.CharField(max_length=5, default="USD")
    vat_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=0.00,
                                          help_text="VAT % applied to rooms and products.")

    # ---- Editable Home page content (hero) ----
    home_hero_title = models.CharField(max_length=150, blank=True, default="Welcome to Grand Hotel")
    home_hero_subtitle = models.TextField(blank=True, default="Experience luxury, comfort, and world-class service. Book your perfect getaway today.")
    home_hero_image = models.ImageField(upload_to='site/', blank=True, null=True,
                                        help_text="Background image for the homepage hero section.")

    # ---- Editable About Us page content ----
    about_hero_title = models.CharField(max_length=150, blank=True, default="About Us")
    about_hero_subtitle = models.TextField(blank=True, default="Redefining luxury and hospitality. Experience world-class comfort in the heart of the city.")
    about_hero_image = models.ImageField(upload_to='site/', blank=True, null=True)
    about_heading = models.CharField(max_length=150, blank=True, default="A Legacy of Luxury")
    about_body = models.TextField(blank=True, default="Our hotel started with a simple vision: to create a sanctuary of peace and luxury for travelers.")
    about_image = models.ImageField(upload_to='site/', blank=True, null=True)
    about_map_embed = models.TextField(blank=True,
                                       help_text="Google Maps embed link (the src URL of the iframe) for the hotel location.")
    contact_address = models.TextField(blank=True, default="")
    contact_phone = models.CharField(max_length=30, blank=True, default="")
    contact_email = models.EmailField(blank=True, default="")

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

    @property
    def about_map_src(self):
        """
        Return a clean Google Maps embed URL even if the admin pasted the
        full `<iframe ...>` HTML. This avoids the "refused to connect" error
        that happens when the entire iframe markup ends up inside src=.
        """
        raw = (self.about_map_embed or '').strip()
        if not raw:
            return ''
        low = raw.lower()
        if '<iframe' in low:
            import re
            m = re.search(r'src=["\']([^"\']+)["\']', raw, flags=re.IGNORECASE)
            if m:
                return m.group(1)
            return ''
        return raw


# ---------------------------------------------------------------------------
# EXPENSES (Admin + Manager) — salaries, repairs, bills, etc.
# ---------------------------------------------------------------------------
class Expense(models.Model):
    CATEGORY_CHOICES = [
        ('salary', 'Staff Salaries'),
        ('repairs', 'Hotel Repairs / Maintenance'),
        ('electricity', 'Electricity Bill'),
        ('water', 'Water Bill'),
        ('supplies', 'Supplies / Inventory Purchase'),
        ('marketing', 'Marketing'),
        ('rent', 'Rent / Lease'),
        ('other', 'Other'),
    ]

    title = models.CharField(max_length=150)
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, default='other')
    amount = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    spent_on = models.DateField()
    note = models.TextField(blank=True)
    branch = models.ForeignKey('Branch', on_delete=models.SET_NULL, null=True, blank=True, related_name='expenses')
    recorded_by = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True, blank=True, related_name='expenses')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-spent_on', '-id']

    def __str__(self):
        return f"{self.get_category_display()} - {self.amount} ({self.spent_on})"


# ---------------------------------------------------------------------------
# ROOM IMAGE GALLERY (multiple images per room -> carousel)
# ---------------------------------------------------------------------------
class RoomImage(models.Model):
    room = models.ForeignKey(Room, on_delete=models.CASCADE, related_name='gallery')
    image = models.ImageField(upload_to='room_images/')
    caption = models.CharField(max_length=120, blank=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['sort_order', 'id']

    def __str__(self):
        return f"Image for Room {self.room.room_number}"


# ---------------------------------------------------------------------------
# KITCHEN INGREDIENT INVENTORY
# ---------------------------------------------------------------------------
class Ingredient(models.Model):
    UNIT_CHOICES = [
        ('kg', 'Kilogram'),
        ('g', 'Gram'),
        ('l', 'Litre'),
        ('ml', 'Millilitre'),
        ('pcs', 'Pieces'),
        ('pack', 'Pack'),
        ('dozen', 'Dozen'),
    ]
    name = models.CharField(max_length=100)
    unit = models.CharField(max_length=10, choices=UNIT_CHOICES, default='pcs')
    cost_price = models.DecimalField(max_digits=10, decimal_places=2, default=0.00,
                                     help_text="Cost per unit (for accounting).")
    stock_quantity = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    low_stock_threshold = models.DecimalField(max_digits=10, decimal_places=2, default=5,
                                              help_text="Alert when stock falls to or below this level.")
    expiry_date = models.DateField(null=True, blank=True)
    branch = models.ForeignKey('Branch', on_delete=models.SET_NULL, null=True, blank=True, related_name='ingredients')
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return f"{self.name} ({self.stock_quantity} {self.unit})"

    @property
    def is_low_stock(self):
        return self.stock_quantity <= (self.low_stock_threshold or 0)

    @property
    def is_expired(self):
        from django.utils import timezone
        return bool(self.expiry_date and self.expiry_date < timezone.now().date())


class IngredientStockTransaction(models.Model):
    ingredient = models.ForeignKey(Ingredient, on_delete=models.CASCADE, related_name='stock_transactions')
    quantity = models.DecimalField(max_digits=10, decimal_places=2,
                                   help_text="Positive for restock, negative for usage/adjustment")
    note = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.ingredient.name}: {self.quantity:+}"


# ---------------------------------------------------------------------------
# LAUNDRY MODULE
# ---------------------------------------------------------------------------
class LaundryService(models.Model):
    SERVICE_CHOICES = [
        ('wash', 'Wash'),
        ('iron', 'Iron'),
        ('starch', 'Starch'),
        ('dryclean', 'Dry Clean'),
        ('sewing', 'Sewing'),
        ('fold', 'Fold & Pack'),
    ]
    name = models.CharField(max_length=100)
    service_type = models.CharField(max_length=20, choices=SERVICE_CHOICES, default='wash')
    price = models.DecimalField(max_digits=8, decimal_places=2, default=0.00)
    cost_price = models.DecimalField(max_digits=8, decimal_places=2, default=0.00,
                                     help_text="Cost to the hotel (for profit calculation).")
    description = models.CharField(max_length=200, blank=True)
    is_available = models.BooleanField(default=True)
    branch = models.ForeignKey('Branch', on_delete=models.SET_NULL, null=True, blank=True, related_name='laundry_services')

    class Meta:
        ordering = ['service_type', 'name']

    def __str__(self):
        return f"{self.name} ({self.get_service_type_display()})"

    @property
    def profit_per_unit(self):
        return (self.price or 0) - (self.cost_price or 0)


class LaundryOrder(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('ready', 'Ready'),
        ('delivered', 'Delivered'),
    ]
    booking = models.ForeignKey(Booking, on_delete=models.CASCADE, related_name='laundry_orders')
    total_price = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    is_paid = models.BooleanField(default=False)
    note = models.CharField(max_length=255, blank=True)
    handled_by = models.ForeignKey(Employee, on_delete=models.SET_NULL, null=True, blank=True, related_name='laundry_orders')
    branch = models.ForeignKey('Branch', on_delete=models.SET_NULL, null=True, blank=True, related_name='laundry_orders')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Laundry Order #{self.id} - Room {self.booking.room.room_number}"


class LaundryOrderItem(models.Model):
    order = models.ForeignKey(LaundryOrder, on_delete=models.CASCADE, related_name='items')
    service = models.ForeignKey(LaundryService, on_delete=models.SET_NULL, null=True)
    quantity = models.PositiveIntegerField(default=1)
    price = models.DecimalField(max_digits=8, decimal_places=2, default=0.00)

    def __str__(self):
        return f"{self.quantity} x {self.service.name if self.service else 'Service'}"

    @property
    def subtotal(self):
        return self.quantity * self.price


# ---------------------------------------------------------------------------
# NOTIFICATIONS (bell icon alerts, role-targeted, with sound)
# ---------------------------------------------------------------------------
class Notification(models.Model):
    TYPE_CHOICES = [
        ('bar_expiry', 'Bar Product Expiration'),
        ('low_stock', 'Low Stock / Restock Due'),
        ('new_booking', 'New Guest Booking'),
        ('cancel_booking', 'Cancelled Booking'),
        ('new_message', 'New Message'),
        ('new_kitchen_order', 'New Kitchen Order'),
        ('new_bar_order', 'New Bar Order'),
        ('new_laundry_order', 'New Laundry Order'),
        ('new_spa_order', 'New Spa Order'),
        ('wallet_topup', 'Wallet Top-up Receipt'),
    ]
    recipient = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='notifications')
    notif_type = models.CharField(max_length=30, choices=TYPE_CHOICES)
    title = models.CharField(max_length=150)
    body = models.CharField(max_length=255, blank=True)
    link = models.CharField(max_length=255, blank=True)
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.get_notif_type_display()} -> {self.recipient.username}"

    @property
    def icon(self):
        return {
            'bar_expiry': 'alert-triangle',
            'low_stock': 'package',
            'new_booking': 'calendar-plus',
            'cancel_booking': 'calendar-x',
            'new_message': 'mail',
            'new_kitchen_order': 'utensils',
            'new_bar_order': 'wine',
            'new_laundry_order': 'shirt',
            'new_spa_order': 'flower-2',
            'wallet_topup': 'wallet',
        }.get(self.notif_type, 'bell')


# ---------------------------------------------------------------------------
# WALLET TOP-UP: guest uploads bank-transfer receipt -> staff confirms
# ---------------------------------------------------------------------------
class WalletTopUpReceipt(models.Model):
    STATUS_PENDING = 'pending'
    STATUS_CONFIRMED = 'confirmed'
    STATUS_REJECTED = 'rejected'

    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending Confirmation'),
        (STATUS_CONFIRMED, 'Confirmed'),
        (STATUS_REJECTED, 'Rejected'),
    ]

    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='wallet_topups')
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    receipt_file = models.FileField(upload_to='wallet_topups/')
    note = models.CharField(max_length=255, blank=True,
                            help_text="Bank reference / transaction ID")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    reviewed_by = models.ForeignKey(CustomUser, on_delete=models.SET_NULL,
                                    null=True, blank=True, related_name='wallet_topups_reviewed')
    review_note = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.user.username} top-up {self.amount} ({self.get_status_display()})"


# ---------------------------------------------------------------------------
# KITCHEN INGREDIENT USAGE TRACKER
# ---------------------------------------------------------------------------
class IngredientUsage(models.Model):
    """Log of ingredients used by the kitchen for daily cooking."""
    ingredient = models.ForeignKey(Ingredient, on_delete=models.CASCADE, related_name='usages')
    quantity = models.DecimalField(max_digits=10, decimal_places=2,
                                   help_text="How much was used (in the ingredient's unit).")
    unit_cost = models.DecimalField(max_digits=10, decimal_places=2, default=0,
                                    help_text="Cost per unit at the time of usage (for accounting).")
    note = models.CharField(max_length=255, blank=True,
                            help_text="e.g. dish / meal it was used for.")
    used_on = models.DateField(default=timezone.now,
                               help_text="The date the ingredient was used.")
    used_by = models.ForeignKey(CustomUser, on_delete=models.SET_NULL,
                                null=True, blank=True, related_name='ingredient_usages')
    branch = models.ForeignKey('Branch', on_delete=models.SET_NULL, null=True, blank=True,
                               related_name='ingredient_usages')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-used_on', '-id']

    def __str__(self):
        return f"{self.ingredient.name}: {self.quantity} ({self.used_on})"

    @property
    def total_cost(self):
        return (self.unit_cost or Decimal('0')) * (self.quantity or Decimal('0'))


# ---------------------------------------------------------------------------
# SPA MODULE
# ---------------------------------------------------------------------------
class SpaService(models.Model):
    CATEGORY_CHOICES = [
        ('massage', 'Massage'),
        ('facial', 'Facial'),
        ('body', 'Body Treatment'),
        ('manicure', 'Manicure / Pedicure'),
        ('sauna', 'Sauna / Steam'),
        ('package', 'Spa Package'),
        ('other', 'Other'),
    ]
    name = models.CharField(max_length=100)
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, default='massage')
    duration_minutes = models.PositiveIntegerField(default=60, help_text="Estimated duration in minutes.")
    price = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    cost_price = models.DecimalField(max_digits=8, decimal_places=2, default=0,
                                     help_text="Therapist cost / supplies (for profit calc).")
    description = models.CharField(max_length=255, blank=True)
    image = models.ImageField(upload_to='spa_images/', blank=True, null=True)
    is_available = models.BooleanField(default=True)
    branch = models.ForeignKey('Branch', on_delete=models.SET_NULL, null=True, blank=True,
                               related_name='spa_services')

    class Meta:
        ordering = ['category', 'name']

    def __str__(self):
        return f"{self.name} ({self.get_category_display()})"

    @property
    def profit_per_unit(self):
        return (self.price or Decimal('0')) - (self.cost_price or Decimal('0'))


class SpaOrder(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('scheduled', 'Scheduled'),
        ('in_progress', 'In Progress'),
        ('completed', 'Completed'),
    ]
    booking = models.ForeignKey(Booking, on_delete=models.CASCADE, related_name='spa_orders')
    total_price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    is_paid = models.BooleanField(default=False)
    note = models.CharField(max_length=255, blank=True)
    appointment_at = models.DateTimeField(blank=True, null=True)
    handled_by = models.ForeignKey(Employee, on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name='spa_orders')
    branch = models.ForeignKey('Branch', on_delete=models.SET_NULL, null=True, blank=True,
                               related_name='spa_orders')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Spa Order #{self.id} - Room {self.booking.room.room_number}"


class SpaOrderItem(models.Model):
    order = models.ForeignKey(SpaOrder, on_delete=models.CASCADE, related_name='items')
    service = models.ForeignKey(SpaService, on_delete=models.SET_NULL, null=True)
    quantity = models.PositiveIntegerField(default=1)
    price = models.DecimalField(max_digits=8, decimal_places=2, default=0)

    def __str__(self):
        return f"{self.quantity} x {self.service.name if self.service else 'Service'}"

    @property
    def subtotal(self):
        return (self.price or Decimal('0')) * self.quantity


# ---------------------------------------------------------------------------
# AUDIT LOG (admin & manager visibility into staff actions)
# ---------------------------------------------------------------------------
class AuditLog(models.Model):
    """Generic activity log for staff actions across the system."""
    ACTION_CHOICES = [
        ('create', 'Create'),
        ('update', 'Update'),
        ('delete', 'Delete'),
        ('status', 'Status Change'),
        ('payment', 'Payment'),
        ('login', 'Login'),
        ('logout', 'Logout'),
        ('other', 'Other'),
    ]
    user = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True, blank=True,
                             related_name='audit_logs')
    action = models.CharField(max_length=20, choices=ACTION_CHOICES, default='other')
    module = models.CharField(max_length=50,
                              help_text="e.g. Booking, Drink, Ingredient, LaundryOrder.")
    summary = models.CharField(max_length=255)
    object_repr = models.CharField(max_length=120, blank=True)
    object_id = models.CharField(max_length=40, blank=True)
    branch = models.ForeignKey('Branch', on_delete=models.SET_NULL, null=True, blank=True,
                               related_name='audit_logs')
    ip_address = models.GenericIPAddressField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"[{self.action}] {self.summary}"