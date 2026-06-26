# 🏨 Hotel Management System

A modern, role-based hotel management web app built with **Django** and **Tailwind CSS**.
It connects **Admin, Manager, Front Desk, Kitchen, Bar, Housekeeping, Spa** and **Guests**
on a single platform — bookings, orders, inventory, laundry, spa, wallet, accounting,
notifications and multi-branch support.

---

## 🧒 Super Simple Setup (follow these steps in order)

> You do **not** need to be a programmer. Just copy each command, paste it, and press **Enter**.
> Do the steps **one at a time**, from top to bottom.

### ✅ Step 0 — Install Python (only once, skip if you already have it)

1. Go to **https://www.python.org/downloads/**
2. Click the big yellow **Download Python** button.
3. Run the downloaded file. **VERY IMPORTANT:** on the first screen, tick the box
   that says **“Add Python to PATH”**, then click **Install Now**.
4. To check it worked, open a terminal (see Step 1) and type:

   ```bash
   python --version
   ```

   If you see something like `Python 3.12.x`, you're good. ✅

### ✅ Step 1 — Open a terminal

- **Windows:** Press the `Windows` key, type **PowerShell**, and click **Windows PowerShell**.
- **Mac:** Press `Cmd + Space`, type **Terminal**, and press Enter.
- **Linux:** Press `Ctrl + Alt + T`.

### ✅ Step 2 — Get the project onto your computer

**Option A — Download as ZIP (easiest, no extra tools):**
1. Open **https://github.com/sumitkumar1503/HotelManagementSystemProject**
2. Click the green **Code** button → **Download ZIP**.
3. Unzip the file (right‑click → Extract All).
4. Remember where you put the folder.

**Option B — With Git (if you have Git installed):**
```bash
git clone https://github.com/sumitkumar1503/HotelManagementSystemProject.git
```

### ✅ Step 3 — Go into the project folder

In the terminal, type `cd ` (with a space) and then the path to the folder. Example:

```bash
cd "C:\Users\YourName\Downloads\HotelManagementSystemProject"
```

> 💡 Tip: You can drag‑and‑drop the folder onto the terminal window to paste its path automatically.

You're in the right place if this command shows a file named `manage.py`:

```bash
# Windows
dir
# Mac/Linux
ls
```

### ✅ Step 4 — Create a virtual environment (a private box for this app)

```bash
python -m venv venv
```

### ✅ Step 5 — Turn the virtual environment ON

```bash
# Windows (PowerShell)
venv\Scripts\Activate.ps1

# Windows (Command Prompt / cmd)
venv\Scripts\activate.bat

# Mac/Linux
source venv/bin/activate
```

After this, your terminal line should start with **`(venv)`**. That means it's ON. ✅

> ⚠️ Windows error “running scripts is disabled on this system”? Run this once, then redo Step 5:
> ```bash
> Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
> ```

### ✅ Step 6 — Install the project's requirements

```bash
pip install -r requirements.txt
```

(This installs Django and Pillow. It may take a minute.)

### ✅ Step 7 — Set up the database

```bash
python manage.py migrate
```

### ✅ Step 8 — Create your admin (boss) login

```bash
python manage.py createsuperuser
```

It will ask for a **username**, **email** (optional, just press Enter to skip),
and a **password** (you won't see the password as you type — that's normal). Remember these!

### ✅ Step 9 — Start the website

```bash
python manage.py runserver
```

You'll see a line like `Starting development server at http://127.0.0.1:8000/`.

### ✅ Step 10 — Open it in your browser

Open your web browser and visit:

👉 **http://127.0.0.1:8000/**

To open the dashboard, go to **http://127.0.0.1:8000/login/** and sign in with the
username and password you made in Step 8.

🎉 **Done! The hotel system is running on your computer.**

---

## 🔁 How to run it again next time

You only do Steps 0–8 **once**. After that, every time you want to start the app:

1. Open a terminal.
2. Go to the project folder (Step 3).
3. Turn the virtual environment on (Step 5).
4. Run the server:
   ```bash
   python manage.py runserver
   ```
5. Open **http://127.0.0.1:8000/**.

To **stop** the server, click the terminal and press `Ctrl + C`.

---

## 🔐 Logging in & user roles

- **Admin** is the account you created with `createsuperuser`. Admins can add staff
  (Managers, Receptionists, Kitchen, Bar, Housekeeping, Spa) from the dashboard.
- **Guests** can create their own account using the **Sign up** link on the website.
- **Forgot your password?** Use the **“Forgot password?”** link on the login page —
  enter your username + registered email to set a new one (no email server needed).

> 💡 Forgot the admin password from the terminal? Run:
> ```bash
> python manage.py changepassword <your-admin-username>
> ```

---

## 🧯 Common problems & quick fixes

| Problem | Fix |
|--------|-----|
| `python` is not recognized | You skipped “Add Python to PATH” in Step 0. Reinstall Python and tick that box. |
| `(venv)` doesn't appear | Re-run Step 5. On Windows PowerShell, see the ExecutionPolicy note in Step 6. |
| `No module named django` | Make sure `(venv)` is ON, then run `pip install -r requirements.txt` again. |
| Port 8000 already in use | Run on another port: `python manage.py runserver 8001` and visit `http://127.0.0.1:8001/`. |
| Images/logos don't show | Make sure you started the server with `python manage.py runserver` (debug mode serves media). |
| Page looks unstyled | The app uses Tailwind via CDN — make sure you have an internet connection. |

---

## ✨ Main Features

- **Multi-branch** hotel/shortlet management with per-branch data and a branch switcher
- **Guest portal:** browse & search rooms (by name, location, price, dates), book, order
  Food / Drinks / Laundry / Spa, credit wallet (with bank-transfer top-up)
- **Room search & filter bar** for both logged-in and non-logged-in guests
- **Front Desk:** walk-in bookings, check-in/out, billing, printable invoices, wallet top-up review
- **Kitchen:** live order display, ingredient inventory, usage tracker, low-stock & expiry alerts
- **Bar:** drink inventory, stock & expiry tracking, product history, CSV import/export
- **Housekeeping:** dirty-room board, one-click clean, cleaning history
- **Spa & Laundry:** service menus, guest ordering, staff monitoring
- **Accounting & Report:** revenue/profit from rooms, food, bar, laundry and **spa**, expenses,
  with day / month / year filters
- **Manager:** sees & switches only the branches the admin assigns; no access to the Branches module
- **Notifications:** role-targeted bell alerts with sound for new orders, bookings, messages, low stock
- **Audit Log:** tracks staff activity (admin/manager)
- **Business & branch identity:** business name + logo on every dashboard, with the current branch beside it

---

## 🛠️ Tech Stack

| Area | Technology |
|------|------------|
| Backend | Django 6, Python 3.12+ |
| Frontend | HTML, Tailwind CSS (CDN), JavaScript |
| Database | SQLite (default) — PostgreSQL compatible |
| Icons | Lucide, Font Awesome |
| Images | Pillow |

---

## 📁 Project Structure (quick map)

```
HotelManagementSystemProject/
├── manage.py               # Django command runner
├── requirements.txt        # Python packages to install
├── db.sqlite3              # The database (created after Step 7)
├── hotel_project/          # Project settings & URLs
├── accounts/               # Main app: models, views, forms, migrations
├── templates/              # All HTML pages
└── media/                  # Uploaded images (logos, room photos, receipts)
```

---

Built with Django + Tailwind CSS. ❤️
