from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.db import transaction
from .models import (
    Booking, CustomUser, Customer, Employee, FoodItem, PaymentSetting, PaymentReceipt,
    Branch, Drink, Message, SiteSetting, Expense,
)


from .models import Room
class FoodItemForm(forms.ModelForm):
    class Meta:
        model = FoodItem
        fields = ['name', 'category', 'price', 'image', 'is_available']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-input'}),
            'category': forms.Select(attrs={'class': 'form-select'}),
            'price': forms.NumberInput(attrs={'class': 'form-input'}),
            'image': forms.FileInput(attrs={'class': 'form-input'}),
            'is_available': forms.CheckboxInput(attrs={'class': 'form-checkbox'}),
        }
class RoomForm(forms.ModelForm):
    class Meta:
        model = Room
        fields = ['room_number', 'room_type', 'price_per_night', 'capacity', 'description', 'room_image', 'room_status']
        widgets = {
            'room_number': forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'e.g. 101'}),
            'room_type': forms.Select(attrs={'class': 'form-select'}),
            'price_per_night': forms.NumberInput(attrs={'class': 'form-input', 'placeholder': '0.00'}),
            'capacity': forms.NumberInput(attrs={'class': 'form-input'}),
            'description': forms.Textarea(attrs={'class': 'form-input', 'rows': 3, 'placeholder': 'Room features, view, etc.'}),
            'room_image': forms.FileInput(attrs={'class': 'form-input'}),
            'room_status': forms.Select(attrs={'class': 'form-select'}),
        }
class EmployeeCreationForm(UserCreationForm):
    # 1. Standard User Fields
    first_name = forms.CharField(required=True, widget=forms.TextInput(attrs={'class': 'form-input'}))
    last_name = forms.CharField(required=True, widget=forms.TextInput(attrs={'class': 'form-input'}))
    email = forms.EmailField(required=True, widget=forms.EmailInput(attrs={'class': 'form-input'}))
    mobile = forms.CharField(required=True, widget=forms.TextInput(attrs={'class': 'form-input'}))
    profile_picture = forms.ImageField(required=False, widget=forms.FileInput(attrs={'class': 'form-input'}))

    # 2. Employee Specific Fields
    job_type = forms.ChoiceField(choices=Employee.JOB_CHOICES, widget=forms.Select(attrs={'class': 'form-select'}))
    salary = forms.DecimalField(max_digits=10, decimal_places=2, widget=forms.NumberInput(attrs={'class': 'form-input'}))
    id_card_number = forms.CharField(max_length=20, widget=forms.TextInput(attrs={'class': 'form-input'}))
    years_of_experience = forms.IntegerField(min_value=0, widget=forms.NumberInput(attrs={'class': 'form-input'}))
    branch = forms.ModelChoiceField(queryset=Branch.objects.all(), required=False,
                                    widget=forms.Select(attrs={'class': 'form-select'}), empty_label="No Branch")

    class Meta(UserCreationForm.Meta):
        model = CustomUser
        fields = UserCreationForm.Meta.fields + ('first_name', 'last_name', 'email', 'mobile', 'profile_picture')

    @transaction.atomic
    def save(self, commit=True):
        # 1. Save the User
        user = super().save(commit=False)
        user.role = 'employee'  # Force role to Employee
        user.email = self.cleaned_data['email']
        user.first_name = self.cleaned_data['first_name']
        user.last_name = self.cleaned_data['last_name']
        user.mobile = self.cleaned_data['mobile']
        user.profile_picture = self.cleaned_data['profile_picture']
        
        if commit:
            user.save()
            # 2. Create the Employee Profile
            Employee.objects.create(
                user=user,
                job_type=self.cleaned_data['job_type'],
                salary=self.cleaned_data['salary'],
                id_card_number=self.cleaned_data['id_card_number'],
                years_of_experience=self.cleaned_data['years_of_experience'],
                branch=self.cleaned_data.get('branch'),
            )
        return user

class EmployeeEditForm(forms.ModelForm):
    # Employee Profile Fields
    job_type = forms.ChoiceField(choices=Employee.JOB_CHOICES, widget=forms.Select(attrs={'class': 'form-select'}))
    salary = forms.DecimalField(max_digits=10, decimal_places=2, widget=forms.NumberInput(attrs={'class': 'form-input'}))
    id_card_number = forms.CharField(max_length=20, widget=forms.TextInput(attrs={'class': 'form-input'}))
    years_of_experience = forms.IntegerField(min_value=0, widget=forms.NumberInput(attrs={'class': 'form-input'}))
    branch = forms.ModelChoiceField(queryset=Branch.objects.all(), required=False,
                                    widget=forms.Select(attrs={'class': 'form-select'}), empty_label="No Branch")

    class Meta:
        model = CustomUser
        fields = ('first_name', 'last_name', 'email', 'mobile', 'profile_picture')
        widgets = {
            'first_name': forms.TextInput(attrs={'class': 'form-input'}),
            'last_name': forms.TextInput(attrs={'class': 'form-input'}),
            'email': forms.EmailInput(attrs={'class': 'form-input'}),
            'mobile': forms.TextInput(attrs={'class': 'form-input'}),
            'profile_picture': forms.FileInput(attrs={'class': 'form-input'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Pre-fill the specific Employee fields from the related profile
        if self.instance.pk and hasattr(self.instance, 'employee_profile'):
            profile = self.instance.employee_profile
            self.fields['job_type'].initial = profile.job_type
            self.fields['salary'].initial = profile.salary
            self.fields['id_card_number'].initial = profile.id_card_number
            self.fields['years_of_experience'].initial = profile.years_of_experience
            self.fields['branch'].initial = profile.branch

    def save(self, commit=True):
        # 1. Save User fields
        user = super().save(commit=commit)
        
        # 2. Save Employee Profile fields
        if hasattr(user, 'employee_profile'):
            profile = user.employee_profile
            profile.job_type = self.cleaned_data['job_type']
            profile.salary = self.cleaned_data['salary']
            profile.id_card_number = self.cleaned_data['id_card_number']
            profile.years_of_experience = self.cleaned_data['years_of_experience']
            profile.branch = self.cleaned_data.get('branch')
            profile.save()
        return user


class WalkInBookingForm(forms.Form):
    # Guest Details
    first_name = forms.CharField(max_length=30, widget=forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'Guest First Name'}))
    last_name = forms.CharField(max_length=30, widget=forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'Guest Last Name'}))
    mobile = forms.CharField(max_length=15, widget=forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'Mobile Number'}))
    email = forms.EmailField(required=False, widget=forms.EmailInput(attrs={'class': 'form-input', 'placeholder': 'Email (Optional)'}))
    
    # Booking Details
    room = forms.ModelChoiceField(
        queryset=Room.objects.filter(room_status='available'), 
        widget=forms.Select(attrs={'class': 'form-select'}),
        empty_label="Select Available Room"
    )
    check_in = forms.DateField(widget=forms.DateInput(attrs={'type': 'date', 'class': 'form-input'}))
    check_out = forms.DateField(widget=forms.DateInput(attrs={'type': 'date', 'class': 'form-input'}))

    def clean(self):
        cleaned_data = super().clean()
        check_in = cleaned_data.get('check_in')
        check_out = cleaned_data.get('check_out')
        if check_in and check_out and check_in >= check_out:
            raise forms.ValidationError("Check-out date must be after check-in.")
        return cleaned_data

class CustomerSignUpForm(UserCreationForm):
    mobile = forms.CharField(required=True)
    address = forms.CharField(widget=forms.Textarea, required=True)
    profile_picture = forms.ImageField(required=False)

    class Meta(UserCreationForm.Meta):
        model = CustomUser
        fields = UserCreationForm.Meta.fields + ('mobile', 'profile_picture', 'email', 'first_name', 'last_name')

    @transaction.atomic
    def save(self):
        user = super().save(commit=False)
        user.role = 'customer'
        user.mobile = self.cleaned_data.get('mobile')
        user.profile_picture = self.cleaned_data.get('profile_picture')
        user.save()
        
        Customer.objects.create(
            user=user,
            address=self.cleaned_data.get('address')
        )
        return user
    

class CustomerEditForm(forms.ModelForm):
    # Fields to edit
    mobile = forms.CharField(required=True, widget=forms.TextInput(attrs={'class': 'form-input'}))
    address = forms.CharField(widget=forms.Textarea(attrs={'class': 'form-input', 'rows': 3}))
    profile_picture = forms.ImageField(required=False, widget=forms.FileInput(attrs={'class': 'form-input'}))

    class Meta:
        model = CustomUser
        fields = ['first_name', 'last_name', 'email', 'mobile', 'profile_picture']
        widgets = {
             'first_name': forms.TextInput(attrs={'class': 'form-input'}),
             'last_name': forms.TextInput(attrs={'class': 'form-input'}),
             'email': forms.EmailInput(attrs={'class': 'form-input'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Pre-fill specific Customer fields
        if self.instance.pk and hasattr(self.instance, 'customer_profile'):
            profile = self.instance.customer_profile
            self.fields['address'].initial = profile.address

    def save(self, commit=True):
        user = super().save(commit=commit)
        if hasattr(user, 'customer_profile'):
            profile = user.customer_profile
            profile.address = self.cleaned_data['address']
            profile.save()
        return user
    
class BookingForm(forms.ModelForm):
    check_in = forms.DateField(widget=forms.DateInput(attrs={'type': 'date', 'class': 'form-input'}))
    check_out = forms.DateField(widget=forms.DateInput(attrs={'type': 'date', 'class': 'form-input'}))

    class Meta:
        model = Booking
        fields = ['check_in', 'check_out']
    
    def clean(self):
        cleaned_data = super().clean()
        check_in = cleaned_data.get('check_in')
        check_out = cleaned_data.get('check_out')

        if check_in and check_out:
            if check_in >= check_out:
                raise forms.ValidationError("Check-out date must be after check-in date.")
        return cleaned_data


class PaymentSettingForm(forms.ModelForm):
    class Meta:
        model = PaymentSetting
        fields = ['bank_name', 'account_holder_name', 'account_number', 'ifsc_code', 'branch', 'payment_link', 'instructions']
        widgets = {
            'bank_name': forms.TextInput(attrs={'class': 'form-input'}),
            'account_holder_name': forms.TextInput(attrs={'class': 'form-input'}),
            'account_number': forms.TextInput(attrs={'class': 'form-input'}),
            'ifsc_code': forms.TextInput(attrs={'class': 'form-input'}),
            'branch': forms.TextInput(attrs={'class': 'form-input'}),
            'payment_link': forms.URLInput(attrs={'class': 'form-input', 'placeholder': 'https://...'}),
            'instructions': forms.Textarea(attrs={'class': 'form-input', 'rows': 3}),
        }


class PaymentReceiptForm(forms.ModelForm):
    class Meta:
        model = PaymentReceipt
        fields = ['receipt_file', 'amount', 'note']
        widgets = {
            'receipt_file': forms.FileInput(attrs={'class': 'form-input'}),
            'amount': forms.NumberInput(attrs={'class': 'form-input', 'step': '0.01', 'placeholder': '0.00'}),
            'note': forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'Transaction ID / reference (optional)'}),
        }


class DrinkForm(forms.ModelForm):
    class Meta:
        model = Drink
        fields = ['name', 'category', 'cost_price', 'price', 'image', 'stock_quantity', 'is_available', 'branch']
        labels = {
            'cost_price': 'Cost Price (what you pay)',
            'price': 'Sale Price (shown to guest)',
        }
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-input'}),
            'category': forms.Select(attrs={'class': 'form-select'}),
            'cost_price': forms.NumberInput(attrs={'class': 'form-input', 'step': '0.01'}),
            'price': forms.NumberInput(attrs={'class': 'form-input', 'step': '0.01'}),
            'image': forms.FileInput(attrs={'class': 'form-input'}),
            'stock_quantity': forms.NumberInput(attrs={'class': 'form-input'}),
            'is_available': forms.CheckboxInput(attrs={'class': 'form-checkbox'}),
            'branch': forms.Select(attrs={'class': 'form-select'}),
        }


class RestockForm(forms.Form):
    quantity = forms.IntegerField(min_value=1, widget=forms.NumberInput(attrs={'class': 'form-input', 'placeholder': 'Qty to add'}))
    note = forms.CharField(required=False, widget=forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'Supplier / note (optional)'}))


class BranchForm(forms.ModelForm):
    class Meta:
        model = Branch
        fields = ['name', 'code', 'address', 'city', 'phone', 'email', 'is_active']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-input'}),
            'code': forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'e.g. NYC01'}),
            'address': forms.Textarea(attrs={'class': 'form-input', 'rows': 2}),
            'city': forms.TextInput(attrs={'class': 'form-input'}),
            'phone': forms.TextInput(attrs={'class': 'form-input'}),
            'email': forms.EmailInput(attrs={'class': 'form-input'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-checkbox'}),
        }


class MessageForm(forms.Form):
    """Compose a message to a department/group, a specific person, or everyone."""
    TARGET_DEPARTMENT = 'department'
    TARGET_INDIVIDUAL = 'individual'
    TARGET_EVERYONE = 'everyone'

    TARGET_CHOICES = [
        (TARGET_DEPARTMENT, 'A department / group'),
        (TARGET_INDIVIDUAL, 'A specific person'),
        (TARGET_EVERYONE, 'Everyone (all guests & staff)'),
    ]

    target_type = forms.ChoiceField(
        choices=TARGET_CHOICES,
        widget=forms.RadioSelect(attrs={'class': 'target-type-radio'}),
        initial=TARGET_DEPARTMENT,
        required=False,
    )
    department = forms.ChoiceField(
        choices=Message.DEPARTMENT_CHOICES,
        widget=forms.Select(attrs={'class': 'form-select'}),
        label="Send to department / group",
        required=False,
    )
    recipient = forms.ModelChoiceField(
        queryset=CustomUser.objects.none(),
        widget=forms.Select(attrs={'class': 'form-select'}),
        label="Send to person",
        required=False,
        empty_label="Select a person...",
    )
    subject = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'Subject (e.g. Fresh towels request)'}),
    )
    body = forms.CharField(
        widget=forms.Textarea(attrs={'class': 'form-input', 'rows': 5, 'placeholder': 'Type your message...'}),
    )

    def __init__(self, *args, user=None, privileged=False, exclude_department=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.privileged = privileged

        # Department choices: drop the sender's own department; guests-as-target
        # is only for privileged senders (admin / manager / receptionist).
        dept_choices = list(Message.DEPARTMENT_CHOICES)
        if exclude_department:
            dept_choices = [c for c in dept_choices if c[0] != exclude_department]
        if not privileged:
            dept_choices = [c for c in dept_choices if c[0] != 'guest']
        self.fields['department'].choices = dept_choices

        if privileged:
            recipients = CustomUser.objects.filter(is_active=True).select_related('employee_profile')
            if user is not None:
                recipients = recipients.exclude(id=user.id)
            self.fields['recipient'].queryset = recipients.order_by('role', 'first_name', 'username')
            self.fields['recipient'].label_from_instance = self._person_label
        else:
            # Non-privileged users can only message a department/group.
            self.fields.pop('target_type')
            self.fields.pop('recipient')

    @staticmethod
    def _person_label(u):
        name = u.get_full_name() or u.username
        if u.role == 'employee' and hasattr(u, 'employee_profile'):
            return f"{name} - {u.employee_profile.get_job_type_display()}"
        return f"{name} - {u.get_role_display()}"

    def clean(self):
        cleaned = super().clean()
        target = cleaned.get('target_type') or self.TARGET_DEPARTMENT
        if target == self.TARGET_INDIVIDUAL and not cleaned.get('recipient'):
            self.add_error('recipient', "Please choose the person to message.")
        if target == self.TARGET_DEPARTMENT and not cleaned.get('department'):
            self.add_error('department', "Please choose a department or group.")
        cleaned['target_type'] = target
        return cleaned


class SiteSettingForm(forms.ModelForm):
    class Meta:
        model = SiteSetting
        fields = ['hotel_name', 'hotel_logo', 'hotel_address', 'hotel_phone', 'hotel_email',
                  'currency_symbol', 'currency_code', 'vat_percentage']
        labels = {
            'hotel_logo': 'Hotel Logo',
            'hotel_address': 'Hotel Address',
            'hotel_phone': 'Contact Phone',
            'hotel_email': 'Contact Email',
        }
        widgets = {
            'hotel_name': forms.TextInput(attrs={'class': 'form-input'}),
            'hotel_logo': forms.FileInput(attrs={'class': 'form-input'}),
            'hotel_address': forms.Textarea(attrs={'class': 'form-input', 'rows': 2}),
            'hotel_phone': forms.TextInput(attrs={'class': 'form-input'}),
            'hotel_email': forms.EmailInput(attrs={'class': 'form-input'}),
            'currency_symbol': forms.TextInput(attrs={'class': 'form-input', 'placeholder': '$, €, ₹, £...'}),
            'currency_code': forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'USD, EUR, INR...'}),
            'vat_percentage': forms.NumberInput(attrs={'class': 'form-input', 'step': '0.01'}),
        }


class ExpenseForm(forms.ModelForm):
    class Meta:
        model = Expense
        fields = ['title', 'category', 'amount', 'spent_on', 'branch', 'note']
        widgets = {
            'title': forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'e.g. June electricity bill'}),
            'category': forms.Select(attrs={'class': 'form-select'}),
            'amount': forms.NumberInput(attrs={'class': 'form-input', 'step': '0.01', 'placeholder': '0.00'}),
            'spent_on': forms.DateInput(attrs={'class': 'form-input', 'type': 'date'}),
            'branch': forms.Select(attrs={'class': 'form-select'}),
            'note': forms.Textarea(attrs={'class': 'form-input', 'rows': 2, 'placeholder': 'Optional details'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['branch'].required = False
        self.fields['branch'].empty_label = "All / No specific branch"


class WalletCreditForm(forms.Form):
    """Admin/Manager adds reward credit to a guest's wallet."""
    amount = forms.DecimalField(
        max_digits=10, decimal_places=2, min_value=0.01,
        widget=forms.NumberInput(attrs={'class': 'form-input', 'step': '0.01', 'placeholder': '0.00'}),
    )
    reason = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'e.g. Loyalty reward'}),
    )