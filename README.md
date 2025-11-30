# 🏨 Grand Hotel Management System

A modern, role-based hotel management web application built with **Django** and **Tailwind CSS**.  
This system streamlines hotel operations by connecting **Front Desk**, **Kitchen**, **Housekeeping**, **Management**, and **Customers** on a single platform.

---

## 🚀 Role-Based Features

The system includes a **Custom User Model** with dedicated dashboards for 5 roles.

---

### 👑 Admin (Manager)

- Analytics Dashboard (Chart.js): Revenue, Occupancy, Room Type Trends  
- Staff Management: Add/Edit/Delete Receptionists, Chefs, Cleaners  
- Room Management: Pricing, Capacity, Type (Single/Double/Suite)  
- Menu Management: Add food items for Room Service  
- Activity Logs: Bookings, Housekeeping, Orders  

---

### 🛎️ Receptionist (Front Desk)

- Real-Time Dashboard: Arrivals, Departures, In-House Guests  
- Smart Alerts: Warning for guests assigned to "Dirty" rooms  
- Walk-In Booking: Create guest + booking in one step  
- Billing & Checkout: Auto-calculate bill (Room + Food)  
- Printable Invoice  

---

### 👨‍🍳 Kitchen Staff

- Live KDS (Kitchen Display System)  
- Update Order Status: Pending → Cooking → Ready → Delivered  
- Orders linked to room numbers  
- Auto billing integration  

---

### 🧹 Housekeeping

- Dirty Room Dashboard  
- One-Click Clean (updates receptionist view)  
- Personal Cleaning History  

---

### 👤 Customer (Guest)

- Online Room Booking  
- Room Service ordering  
- Dashboard: Booking History, Current Bill, Loyalty Tier  

---

## 🛠️ Tech Stack

| Feature | Technology |
|--------|------------|
| Backend | Django 5.x, Python |
| Frontend | HTML, Tailwind CSS (CDN), JavaScript |
| Database | SQLite (Default), PostgreSQL Compatible |
| Charts | Chart.js |
| Icons | Lucide, FontAwesome |
| Media | Pillow |

---

⚙️ Installation & Setup
1️⃣ Clone Repository
git clone https://github.com/yourusername/grand-hotel-system.git
cd grand-hotel-system

2️⃣ Create Virtual Environment
python -m venv venv

# Windows
venv\Scripts\activate

# Mac/Linux
source venv/bin/activate

3️⃣ Install Dependencies
pip install django pillow

4️⃣ Database Setup
python manage.py makemigrations
python manage.py migrate

5️⃣ Create Superuser
python manage.py createsuperuser

6️⃣ Run Server
python manage.py runserver


Visit:
http://127.0.0.1:8000/

❤️ Built With

Django + clean UI + passion for hotel automation