from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.db import transaction
from .models import (
    Booking, CustomUser, Customer, Employee, FoodItem, PaymentSetting, PaymentReceipt,
    Branch, Drink, Message, SiteSetting,
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
        fields = ['name', 'category', 'price', 'image', 'stock_quantity', 'is_available', 'branch']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-input'}),
            'category': forms.Select(attrs={'class': 'form-select'}),
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


class MessageForm(forms.ModelForm):
    class Meta:
        model = Message
        fields = ['recipient', 'subject', 'body']
        widgets = {
            'recipient': forms.Select(attrs={'class': 'form-select'}),
            'subject': forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'Subject (e.g. Fresh towels request)'}),
            'body': forms.Textarea(attrs={'class': 'form-input', 'rows': 5, 'placeholder': 'Type your message...'}),
        }

    def __init__(self, *args, sender=None, **kwargs):
        super().__init__(*args, **kwargs)
        qs = CustomUser.objects.exclude(is_active=False).order_by('role', 'username')
        if sender is not None:
            qs = qs.exclude(id=sender.id)
        self.fields['recipient'].queryset = qs
        self.fields['recipient'].label_from_instance = self._label

    @staticmethod
    def _label(user):
        name = user.get_full_name() or user.username
        if user.role == 'employee' and hasattr(user, 'employee_profile'):
            return f"{name} ({user.employee_profile.get_job_type_display()})"
        return f"{name} ({user.get_role_display()})"


class SiteSettingForm(forms.ModelForm):
    class Meta:
        model = SiteSetting
        fields = ['hotel_name', 'currency_symbol', 'currency_code', 'vat_percentage']
        widgets = {
            'hotel_name': forms.TextInput(attrs={'class': 'form-input'}),
            'currency_symbol': forms.TextInput(attrs={'class': 'form-input', 'placeholder': '$, €, ₹, £...'}),
            'currency_code': forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'USD, EUR, INR...'}),
            'vat_percentage': forms.NumberInput(attrs={'class': 'form-input', 'step': '0.01'}),
        }