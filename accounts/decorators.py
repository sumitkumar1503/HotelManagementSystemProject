from django.http import HttpResponseForbidden
from django.shortcuts import redirect
from django.contrib import messages
from django.contrib.auth import logout
from django.core.exceptions import ObjectDoesNotExist

def admin_required(view_func):
    def wrapper_func(request, *args, **kwargs):
        if request.user.is_authenticated and request.user.role == 'admin':
            return view_func(request, *args, **kwargs)
        return HttpResponseForbidden("Access Denied: You are not an Admin.")
    return wrapper_func

def customer_required(view_func):
    def wrapper_func(request, *args, **kwargs):
        if request.user.is_authenticated and request.user.role == 'customer':
            return view_func(request, *args, **kwargs)
        return redirect('login')
    return wrapper_func

def employee_required(allowed_jobs=[]):
    """
    Checks if user is an Employee AND has the correct Job Type.
    Safe-guards against missing profiles.
    """
    def decorator(view_func):
        def wrapper_func(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect('login')

            # 1. Admin Override (Optional: allows admin to view employee pages)
            if request.user.role == 'admin':
                return view_func(request, *args, **kwargs)

            # 2. Check Employee Access
            if request.user.role == 'employee':
                try:
                    # Attempt to access the profile
                    profile = request.user.employee_profile
                    
                    if profile.job_type in allowed_jobs:
                        return view_func(request, *args, **kwargs)
                    else:
                        # User has a profile but wrong job type
                        return HttpResponseForbidden(f"Access Denied: This area is for {', '.join(allowed_jobs)} only.")
                
                except ObjectDoesNotExist:
                    # --- CRITICAL FIX ---
                    # The user has role='employee' but NO profile data.
                    # We log them out automatically so they can't get stuck here.
                    logout(request)
                    messages.error(request, "Your account setup is incomplete. Please contact Admin or login with a valid staff account.")
                    return redirect('login')
            
            return HttpResponseForbidden("Access Denied: You do not have permission.")
        return wrapper_func
    return decorator