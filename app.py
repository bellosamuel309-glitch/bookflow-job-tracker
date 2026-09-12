import os
import sqlite3
import random
from datetime import datetime
from werkzeug.utils import secure_filename
from flask import Flask, render_template, request, redirect, url_for, jsonify, flash, session, send_from_directory
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from flask_mail import Mail, Message
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'bookflow-enterprise-cryptographic-security-token-key')
DB_FILE = 'database.db'
UPLOAD_FOLDER = 'static/uploads'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'pdf', 'doc', 'docx'}

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# --- MAIL ---
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = os.environ.get('MAIL_USERNAME', 'bellosamuel309@gmail.com')
app.config['MAIL_PASSWORD'] = os.environ.get('MAIL_PASSWORD', 'wmca iczl shnk mjky')
app.config['MAIL_DEFAULT_SENDER'] = ('BookFlow Enterprise Hub', app.config['MAIL_USERNAME'])
mail = Mail(app)

# --- LOGIN ---
login_manager = LoginManager()
login_manager.login_view = 'login'
login_manager.init_app(app)

class User(UserMixin):
    def __init__(self, id, email, role, status):
        self.id = id
        self.email = email
        self.role = role
        self.status = status

    @property
    def is_admin(self): return self.role == 'admin'
    @property
    def is_manager(self): return self.role == 'manager'
    @property
    def is_coordinator(self): return self.role == 'coordinator'
    @property
    def is_technician(self): return self.role == 'technician'
    @property
    def is_customer(self): return self.role == 'customer'
    @property
    def is_staff(self): return self.role in ['admin', 'manager', 'coordinator', 'technician']


def get_db_connection():
    """Safer connection with timeout for Windows"""
    conn = sqlite3.connect(DB_FILE, timeout=20)
    conn.row_factory = sqlite3.Row
    return conn


@login_manager.user_loader
def load_user(user_id):
    conn = get_db_connection()
    user = conn.execute('SELECT * FROM users WHERE user_id = ?', (user_id,)).fetchone()
    conn.close()
    if user and user['status'] != 'banned':
        return User(user['user_id'], user['email'], user['role'], user['status'])
    return None


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def init_db():
    conn = sqlite3.connect(DB_FILE, timeout=20)
    cursor = conn.cursor()

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            role TEXT DEFAULT 'customer' CHECK(role IN ('customer', 'coordinator', 'technician', 'manager', 'admin')),
            status TEXT DEFAULT 'active' CHECK(status IN ('active', 'banned')),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS jobs (
            job_id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_id INTEGER,
            coordinator_id INTEGER,
            assigned_tech_id INTEGER,
            author_name TEXT NOT NULL,
            book_title TEXT NOT NULL,
            service_type TEXT CHECK(service_type IN ('Binding', 'Restoration', 'Digitization', 'Research', 'Printing', 'Special Orders')),
            priority TEXT DEFAULT 'Medium' CHECK(priority IN ('Low', 'Medium', 'High', 'Critical')),
            details TEXT,
            quote_amount REAL DEFAULT 0.0,
            status TEXT DEFAULT 'New' CHECK(status IN ('New', 'Quoted', 'Approved', 'In Progress', 'On Hold', 'Quality Check', 'Completed', 'Closed')),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(customer_id) REFERENCES users(user_id),
            FOREIGN KEY(coordinator_id) REFERENCES users(user_id),
            FOREIGN KEY(assigned_tech_id) REFERENCES users(user_id)
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS activity_log (
            log_id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id INTEGER,
            user_id INTEGER,
            action TEXT,
            old_value TEXT,
            new_value TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(job_id) REFERENCES jobs(job_id),
            FOREIGN KEY(user_id) REFERENCES users(user_id)
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS attachments (
            attachment_id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id INTEGER,
            uploaded_by INTEGER,
            filename TEXT,
            original_name TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(job_id) REFERENCES jobs(job_id),
            FOREIGN KEY(uploaded_by) REFERENCES users(user_id)
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS notes (
            note_id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id INTEGER,
            user_id INTEGER,
            content TEXT,
            is_internal INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(job_id) REFERENCES jobs(job_id),
            FOREIGN KEY(user_id) REFERENCES users(user_id)
        )
    ''')

    # Seed users only if table is empty
    existing = cursor.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    if existing == 0:
        pwd = generate_password_hash('test123')
        cursor.execute("INSERT INTO users (email, password_hash, role) VALUES ('bellosamuel309@gmail.com', ?, 'admin')", (pwd,))
        cursor.execute("INSERT INTO users (email, password_hash, role) VALUES ('manager@flow.com', ?, 'manager')", (pwd,))
        cursor.execute("INSERT INTO users (email, password_hash, role) VALUES ('frontdesk@flow.com', ?, 'coordinator')", (pwd,))
        cursor.execute("INSERT INTO users (email, password_hash, role) VALUES ('artisan@flow.com', ?, 'technician')", (pwd,))

    conn.commit()
    conn.close()


def log_activity(job_id, user_id, action, old_value=None, new_value=None):
    """Always uses its own short-lived connection to avoid locking"""
    conn = get_db_connection()
    try:
        conn.execute('''
            INSERT INTO activity_log (job_id, user_id, action, old_value, new_value)
            VALUES (?, ?, ?, ?, ?)
        ''', (job_id, user_id, action, str(old_value) if old_value else None, str(new_value) if new_value else None))
        conn.commit()
    finally:
        conn.close()


def send_instant_email(recipient, subject, content):
    try:
        msg = Message(subject, recipients=[recipient])
        msg.body = content
        mail.send(msg)
    except Exception as e:
        print(f"SMTP Error: {str(e)}")


# ==================== ROUTES ====================

@app.route('/')
def index():
    return redirect(url_for('login'))

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        # Step 1: Request OTP
        if 'otp' not in request.form:
            email = request.form.get('email', '').strip().lower()
            password = request.form.get('password', '')

            if not email or not password:
                flash('Email and password are required.', 'danger')
                return redirect(url_for('signup'))

            if len(password) < 6:
                flash('Password must be at least 6 characters.', 'danger')
                return redirect(url_for('signup'))

            conn = get_db_connection()
            exists = conn.execute('SELECT 1 FROM users WHERE email = ?', (email,)).fetchone()
            conn.close()

            if exists:
                flash('This email is already registered. Please login instead.', 'danger')
                return redirect(url_for('login'))

            # Generate OTP
            otp = str(random.randint(100000, 999999))
            session['signup_data'] = {
                'email': email,
                'password': password,
                'otp': otp,
                'created_at': datetime.now().timestamp()
            }

            send_instant_email(
                email,
                "BookFlow – Your Verification Code",
                f"Your verification code is: {otp}\n\nThis code expires in 10 minutes."
            )
            flash('A 6-digit verification code has been sent to your email.', 'success')
            return render_template('signup.html', otp_required=True, email=email)

        # Step 2: Verify OTP
        else:
            data = session.get('signup_data')
            user_otp = request.form.get('otp', '').strip()

            if not data:
                flash('Session expired. Please start again.', 'danger')
                return redirect(url_for('signup'))

            # Optional: expire OTP after 10 minutes
            if datetime.now().timestamp() - data.get('created_at', 0) > 600:
                session.pop('signup_data', None)
                flash('Verification code has expired. Please try again.', 'danger')
                return redirect(url_for('signup'))

            if user_otp == data['otp']:
                conn = get_db_connection()
                try:
                    # Double-check email still doesn't exist (race condition protection)
                    exists = conn.execute('SELECT 1 FROM users WHERE email = ?', (data['email'],)).fetchone()
                    if exists:
                        flash('This email was just registered. Please login.', 'danger')
                        return redirect(url_for('login'))

                    conn.execute(
                        "INSERT INTO users (email, password_hash, role) VALUES (?, ?, 'customer')",
                        (data['email'], generate_password_hash(data['password']))
                    )
                    conn.commit()
                finally:
                    conn.close()

                session.pop('signup_data', None)
                flash('Account created successfully! You can now login.', 'success')
                return redirect(url_for('login'))
            else:
                flash('Invalid verification code. Please try again.', 'danger')
                return render_template('signup.html', otp_required=True, email=data['email'])

    return render_template('signup.html', otp_required=False)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email'].strip().lower()
        password = request.form['password']

        conn = get_db_connection()
        user = conn.execute('SELECT * FROM users WHERE email = ?', (email,)).fetchone()
        conn.close()

        if user and user['status'] != 'banned' and check_password_hash(user['password_hash'], password):
            login_user(User(user['user_id'], user['email'], user['role'], user['status']))
            return redirect(url_for('dashboard'))
        flash('Invalid credentials or account banned.', 'danger')
    return render_template('login.html')


@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))


@app.route('/request', methods=['GET', 'POST'])
@login_required
def request_service():
    if request.method == 'POST':
        author_name = request.form['author_name'].strip()
        book_title = request.form['book_title'].strip()
        service_type = request.form['service_type']
        priority = request.form.get('priority', 'Medium')
        details = request.form.get('details', '').strip()

        conn = get_db_connection()
        try:
            cursor = conn.execute('''
                INSERT INTO jobs (customer_id, author_name, book_title, service_type, priority, details, status)
                VALUES (?, ?, ?, ?, ?, ?, 'New')
            ''', (current_user.id, author_name, book_title, service_type, priority, details))
            job_id = cursor.lastrowid

            # Handle file uploads
            files = request.files.getlist('attachments')
            for file in files:
                if file and allowed_file(file.filename):
                    filename = secure_filename(f"{job_id}_{file.filename}")
                    file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                    conn.execute(
                        'INSERT INTO attachments (job_id, uploaded_by, filename, original_name) VALUES (?, ?, ?, ?)',
                        (job_id, current_user.id, filename, file.filename)
                    )

            conn.commit()
        finally:
            conn.close()

        # Call log_activity AFTER closing the connection
        log_activity(job_id, current_user.id, 'Request Created', None, 'New')
        send_instant_email(current_user.email, "Request Received", f"Your request for '{book_title}' has been submitted.")
        flash('Request submitted successfully.', 'success')
        return redirect(url_for('dashboard'))

    return render_template('request.html')


@app.route('/dashboard')
@login_required
def dashboard():
    conn = get_db_connection()

    # Get people who can be assigned jobs
    assignable_users = conn.execute('''
        SELECT user_id, email, role 
        FROM users 
        WHERE role IN ('coordinator', 'technician') AND status = 'active'
        ORDER BY role, email
    ''').fetchall()

    if current_user.role in ['admin', 'manager']:
        # Admin & Manager see ALL jobs
        jobs = conn.execute('''
            SELECT jobs.*, 
                   c.email AS client_email, 
                   t.email AS tech_email,
                   coord.email AS coordinator_email
            FROM jobs
            LEFT JOIN users c ON jobs.customer_id = c.user_id
            LEFT JOIN users t ON jobs.assigned_tech_id = t.user_id
            LEFT JOIN users coord ON jobs.coordinator_id = coord.user_id
            ORDER BY 
                CASE jobs.priority 
                    WHEN 'Critical' THEN 1 
                    WHEN 'High' THEN 2 
                    WHEN 'Medium' THEN 3 
                    ELSE 4 
                END,
                jobs.created_at DESC
        ''').fetchall()

    elif current_user.role == 'coordinator':
        # Front Desk only sees jobs assigned to them
        jobs = conn.execute('''
            SELECT jobs.*, c.email AS client_email
            FROM jobs
            LEFT JOIN users c ON jobs.customer_id = c.user_id
            WHERE jobs.coordinator_id = ?
            ORDER BY jobs.created_at DESC
        ''', (current_user.id,)).fetchall()

    elif current_user.is_technician:
        # Artisan only sees jobs assigned to them
        jobs = conn.execute('''
            SELECT jobs.*, c.email AS client_email
            FROM jobs
            LEFT JOIN users c ON jobs.customer_id = c.user_id
            WHERE jobs.assigned_tech_id = ?
            ORDER BY jobs.created_at DESC
        ''', (current_user.id,)).fetchall()

    else:
        # Customer sees only their own jobs
        jobs = conn.execute('''
            SELECT jobs.*, t.email AS tech_email
            FROM jobs
            LEFT JOIN users t ON jobs.assigned_tech_id = t.user_id
            WHERE jobs.customer_id = ?
            ORDER BY jobs.created_at DESC
        ''', (current_user.id,)).fetchall()

    conn.close()

    return render_template(
        'dashboard.html',
        jobs=jobs,
        assignable_users=assignable_users,
        role=current_user.role
    )

@app.route('/job/<int:job_id>')
@login_required
def job_detail(job_id):
    conn = get_db_connection()
    job = conn.execute('''
        SELECT jobs.*, c.email AS client_email, t.email AS tech_email
        FROM jobs
        LEFT JOIN users c ON jobs.customer_id = c.user_id
        LEFT JOIN users t ON jobs.assigned_tech_id = t.user_id
        WHERE jobs.job_id = ?
    ''', (job_id,)).fetchone()

    if not job:
        conn.close()
        flash('Job not found.', 'danger')
        return redirect(url_for('dashboard'))

    # Permission check
    if current_user.is_customer and job['customer_id'] != current_user.id:
        conn.close()
        flash('Access denied.', 'danger')
        return redirect(url_for('dashboard'))
    if current_user.is_technician and job['assigned_tech_id'] != current_user.id:
        conn.close()
        flash('Access denied.', 'danger')
        return redirect(url_for('dashboard'))

    attachments = conn.execute('SELECT * FROM attachments WHERE job_id = ?', (job_id,)).fetchall()
    notes = conn.execute('''
        SELECT notes.*, users.email 
        FROM notes JOIN users ON notes.user_id = users.user_id
        WHERE notes.job_id = ? 
        ORDER BY notes.created_at DESC
    ''', (job_id,)).fetchall()
    logs = conn.execute('''
        SELECT activity_log.*, users.email 
        FROM activity_log JOIN users ON activity_log.user_id = users.user_id
        WHERE activity_log.job_id = ? 
        ORDER BY activity_log.created_at DESC
    ''', (job_id,)).fetchall()
    techs = conn.execute("SELECT user_id, email FROM users WHERE role = 'technician' AND status = 'active'").fetchall()
    conn.close()

    return render_template('job_detail.html', job=job, attachments=attachments, notes=notes, logs=logs, techs=techs)


@app.route('/api/update-job', methods=['POST'])
@login_required
def update_job():
    data = request.json
    job_id = data.get('job_id')
    new_status = data.get('status')
    tech_id = data.get('tech_id')
    coordinator_id = data.get('coordinator_id')
    priority = data.get('priority')
    quote = data.get('quote_amount')

    conn = get_db_connection()
    
    job = conn.execute('''
        SELECT jobs.*, c.email as client_email 
        FROM jobs 
        JOIN users c ON jobs.customer_id = c.user_id 
        WHERE jobs.job_id = ?
    ''', (job_id,)).fetchone()

    if not job:
        conn.close()
        return jsonify({"success": False, "error": "Job not found"}), 404

    # Permission checks
    if current_user.is_technician and job['assigned_tech_id'] != current_user.id:
        conn.close()
        return jsonify({"success": False, "error": "Unauthorized"}), 403

    if current_user.role == 'coordinator' and job['coordinator_id'] != current_user.id:
        conn.close()
        return jsonify({"success": False, "error": "Unauthorized"}), 403

    try:
        # ========== ADMIN & MANAGER ACTIONS ==========
        if current_user.role in ['admin', 'manager']:

            # Change Status
            if new_status and new_status != job['status']:
                conn.execute(
                    'UPDATE jobs SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE job_id = ?',
                    (new_status, job_id)
                )
                log_activity(job_id, current_user.id, 'Status Changed', job['status'], new_status)
                send_instant_email(
                    job['client_email'],
                    f"Status Update: {job['book_title']}",
                    f"Your job status is now: {new_status}"
                )

            # Assign Technician (Artisan)
            if tech_id is not None:
                new_tech = None if tech_id == "" else int(tech_id)
                conn.execute(
                    'UPDATE jobs SET assigned_tech_id = ?, updated_at = CURRENT_TIMESTAMP WHERE job_id = ?',
                    (new_tech, job_id)
                )
                log_activity(job_id, current_user.id, 'Technician Assigned', job['assigned_tech_id'], new_tech)

            # Assign Coordinator (Front Desk)
            if coordinator_id is not None:
                new_coord = None if coordinator_id == "" else int(coordinator_id)
                conn.execute(
                    'UPDATE jobs SET coordinator_id = ?, updated_at = CURRENT_TIMESTAMP WHERE job_id = ?',
                    (new_coord, job_id)
                )
                log_activity(job_id, current_user.id, 'Coordinator Assigned', job['coordinator_id'], new_coord)

            # Change Priority
            if priority and priority != job['priority']:
                conn.execute(
                    'UPDATE jobs SET priority = ?, updated_at = CURRENT_TIMESTAMP WHERE job_id = ?',
                    (priority, job_id)
                )
                log_activity(job_id, current_user.id, 'Priority Changed', job['priority'], priority)

            # Update Quote
            if quote is not None:
                conn.execute(
                    'UPDATE jobs SET quote_amount = ?, status = ?, updated_at = CURRENT_TIMESTAMP WHERE job_id = ?',
                    (float(quote), 'Quoted', job_id)
                )
                log_activity(job_id, current_user.id, 'Quote Added', job['quote_amount'], quote)
                send_instant_email(
                    job['client_email'],
                    "New Quote Available",
                    f"A quote of ${quote} has been added for '{job['book_title']}'."
                )

        # ========== TECHNICIAN ACTIONS ==========
        elif current_user.is_technician and job['assigned_tech_id'] == current_user.id:
            if new_status and new_status in ['In Progress', 'On Hold', 'Quality Check', 'Completed']:
                conn.execute(
                    'UPDATE jobs SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE job_id = ?',
                    (new_status, job_id)
                )
                log_activity(job_id, current_user.id, 'Status Changed', job['status'], new_status)

        # ========== COORDINATOR (FRONT DESK) ACTIONS ==========
        elif current_user.role == 'coordinator' and job['coordinator_id'] == current_user.id:
            if new_status and new_status in ['In Progress', 'On Hold', 'Quality Check', 'Completed']:
                conn.execute(
                    'UPDATE jobs SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE job_id = ?',
                    (new_status, job_id)
                )
                log_activity(job_id, current_user.id, 'Status Changed', job['status'], new_status)

        # ========== CUSTOMER ACTIONS ==========
        elif current_user.is_customer and job['customer_id'] == current_user.id:
            if new_status == 'Approved' and job['status'] == 'Quoted':
                conn.execute(
                    'UPDATE jobs SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE job_id = ?',
                    ('Approved', job_id)
                )
                log_activity(job_id, current_user.id, 'Quote Approved', 'Quoted', 'Approved')
                send_instant_email(
                    job['client_email'],
                    "Quote Approved",
                    f"You have approved the quote for '{job['book_title']}'."
                )

        conn.commit()

    finally:
        conn.close()

    return jsonify({"success": True})

@app.route('/api/add-note', methods=['POST'])
@login_required
def add_note():
    data = request.json
    job_id = data.get('job_id')
    content = data.get('content', '').strip()
    is_internal = 1 if data.get('is_internal') else 0

    if not content:
        return jsonify({"success": False, "error": "Empty note"}), 400

    conn = get_db_connection()
    try:
        job = conn.execute('SELECT * FROM jobs WHERE job_id = ?', (job_id,)).fetchone()
        if not job:
            return jsonify({"success": False}), 404

        if current_user.is_customer and job['customer_id'] != current_user.id:
            return jsonify({"success": False}), 403

        conn.execute('INSERT INTO notes (job_id, user_id, content, is_internal) VALUES (?, ?, ?, ?)',
                     (job_id, current_user.id, content, is_internal))
        conn.commit()
    finally:
        conn.close()

    return jsonify({"success": True})


# ==================== ADMIN ROUTES ====================

@app.route('/admin')
@login_required
def admin_panel():
    if not (current_user.is_admin or current_user.is_manager):
        flash('Access denied.', 'danger')
        return redirect(url_for('dashboard'))

    conn = get_db_connection()
    users = conn.execute(
        "SELECT user_id, email, role, status, created_at FROM users WHERE user_id != ? ORDER BY user_id",
        (current_user.id,)
    ).fetchall()

    jobs = conn.execute('''
        SELECT jobs.*, c.email AS client_email
        FROM jobs
        LEFT JOIN users c ON jobs.customer_id = c.user_id
        ORDER BY jobs.created_at DESC
    ''').fetchall()
    conn.close()

    return render_template('admin_panel.html',
                           users=users,
                           jobs=jobs,
                           roles=['customer', 'coordinator', 'technician', 'manager', 'admin'])


@app.route('/admin/create-user', methods=['POST'])
@login_required
def admin_create_user():
    if not current_user.is_admin:
        flash('Only Admin can create accounts.', 'danger')
        return redirect(url_for('admin_panel'))

    email = request.form.get('email', '').strip().lower()
    password = request.form.get('password', 'test123')
    role = request.form.get('role', 'customer')

    if not email:
        flash('Email is required.', 'danger')
        return redirect(url_for('admin_panel'))

    conn = get_db_connection()
    existing = conn.execute('SELECT 1 FROM users WHERE email = ?', (email,)).fetchone()
    if existing:
        conn.close()
        flash('Email already exists.', 'danger')
        return redirect(url_for('admin_panel'))

    hashed = generate_password_hash(password)
    conn.execute(
        "INSERT INTO users (email, password_hash, role) VALUES (?, ?, ?)",
        (email, hashed, role)
    )
    conn.commit()
    conn.close()

    flash(f'Account created successfully for {email} ({role}).', 'success')
    return redirect(url_for('admin_panel'))


@app.route('/api/admin/modify-user', methods=['POST'])
@login_required
def modify_user():
    if not (current_user.is_admin or current_user.is_manager):
        return jsonify({"success": False}), 403

    data = request.json
    target_id = data.get('user_id')
    operation = data.get('operation')
    new_role = data.get('role')

    conn = get_db_connection()
    try:
        if operation == 'ban':
            conn.execute("UPDATE users SET status = 'banned' WHERE user_id = ?", (target_id,))
        elif operation == 'unban':
            conn.execute("UPDATE users SET status = 'active' WHERE user_id = ?", (target_id,))
        elif operation == 'role' and new_role and current_user.is_admin:
            conn.execute("UPDATE users SET role = ? WHERE user_id = ?", (new_role, target_id))
        elif operation == 'delete' and current_user.is_admin:
            conn.execute("DELETE FROM jobs WHERE customer_id = ?", (target_id,))
            conn.execute("DELETE FROM users WHERE user_id = ?", (target_id,))
        conn.commit()
    finally:
        conn.close()

    return jsonify({"success": True})


@app.route('/uploads/<filename>')
@login_required
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)


if __name__ == '__main__':
    init_db()
    app.run(debug=True)