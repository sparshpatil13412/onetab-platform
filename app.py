from flask import Flask, render_template, redirect, url_for, session, request, flash, abort
from datetime import timedelta
from flask_sqlalchemy import SQLAlchemy
from flask_wtf import file
from datetime import datetime, timedelta
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from werkzeug.security import generate_password_hash, check_password_hash
from flask import send_from_directory
from werkzeug.utils import secure_filename
from flask_wtf.csrf import CSRFProtect
from werkzeug.utils import safe_join
from dotenv import load_dotenv
import shutil
import uuid
import os

env_path = os.path.join(os.path.dirname(__file__), ".env")
load_dotenv(env_path)

app = Flask(__name__)
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["200 per day", "50 per hour"]
)
app.config['RATELIMIT_HEADERS_ENABLED'] = True
app.secret_key = os.environ.get("SECRET_KEY")
csrf = CSRFProtect(app)

# DB config
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get("DATABASE_URL")
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
    "pool_pre_ping": True
}
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Upload config
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024

app.permanent_session_lifetime = timedelta(days=30)

db = SQLAlchemy(app)

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)   
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)

    failed_attempts = db.Column(db.Integer, default=0)
    locked_until = db.Column(db.DateTime, nullable=True)


class Folder(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    uuid = db.Column(db.String(36), unique=True, default=lambda: str(uuid.uuid4()))
    name = db.Column(db.String(100))
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)


class File(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(200))
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

    folder_id = db.Column(db.Integer, db.ForeignKey('folder.id'), nullable=False)  # INT
    folder_uuid = db.Column(db.String(36), nullable=False)  # UUID

ALLOWED_EXTENSIONS = {'pdf', 'png', 'jpg', 'jpeg', 'docx', 'xlsx'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route("/")
@app.route("/home")
def home():
    if "user_id" in session:
        return redirect(url_for("dashboard"))
    return render_template("index.html")


@app.route('/dashboard')
def dashboard():
    if "user_id" not in session:
        return redirect(url_for("login"))

    folders = Folder.query.filter_by(user_id=session['user_id']).all()

    return render_template(
        "dashboard.html",
        user=session.get('user'),
        email=session.get('email'),
        folders=folders
    )

@app.route('/create_folder', methods=['POST'])
def create_folder():
    if "user_id" not in session:
        return redirect(url_for("login"))

    folder_name = request.form['folder_name']

    new_folder = Folder(
        name=folder_name,
        user_id=session['user_id']
    )

    db.session.add(new_folder)
    db.session.commit()

    flash("Folder created!", "success")
    return redirect(url_for('dashboard'))

@app.route('/upload_page/<string:folder_uuid>')
@limiter.limit("10 per minute")
def upload_page(folder_uuid):
    if "user_id" not in session:
        return redirect(url_for("login"))

    folder = Folder.query.filter_by(uuid=folder_uuid, user_id=session['user_id']).first()

    if not folder or folder.user_id != session['user_id']:
        abort(403)

    return render_template("upload.html", folder=folder)


@app.route('/upload/<string:folder_uuid>', methods=['POST'])
def upload_file(folder_uuid):
    if "user_id" not in session:
        return redirect(url_for('login'))

    folder = Folder.query.filter_by(uuid=folder_uuid, user_id=session['user_id']).first()

    if not folder or folder.user_id != session['user_id']:
        abort(403)

    file = request.files.get('file')

    if file and file.filename != "" and allowed_file(file.filename):
        filename = secure_filename(file.filename)

        user_folder = os.path.join(
            app.config['UPLOAD_FOLDER'],
            f"user_{session['user_id']}",
            f"folder_{folder_uuid}"
        )

        os.makedirs(user_folder, exist_ok=True)

        filepath = os.path.join(user_folder, filename)
        file.save(filepath)

        new_file = File(
            filename=filename,
            user_id=session['user_id'],
            folder_id=folder.id,
            folder_uuid=folder.uuid
        )

        db.session.add(new_file)
        db.session.commit()

        flash("File uploaded!", "success")
    else:
        flash("File of this extension not allowed!","error")

    return redirect(url_for('view_folder', folder_uuid=folder_uuid))

@app.route('/login', methods=['GET', 'POST'])
@limiter.limit("10 per minute")
def login():
    if "user_id" in session:
        return redirect(url_for('dashboard'))

    if request.method == "POST":
        email = request.form['email']
        password = request.form['password']

        user = User.query.filter_by(email=email).first()

        if not user:
            flash("Invalid credentials", "error")
            return redirect(url_for('login'))

        # 🔒 Check lock
        if user.locked_until and datetime.utcnow() < user.locked_until:
            flash("Account locked. Try again later.", "error")
            return redirect(url_for('login'))

        # ✅ Correct password
        if check_password_hash(user.password, password):
            user.failed_attempts = 0
            user.locked_until = None

            session['user_id'] = user.id
            session['user'] = user.name
            session['email'] = user.email

            db.session.commit()
            return redirect(url_for('dashboard'))

        # ❌ Wrong password
        user.failed_attempts += 1

        if user.failed_attempts >= 5:
            user.locked_until = datetime.utcnow() + timedelta(minutes=10)
            flash("Too many attempts. Locked for 10 minutes.", "error")
        else:
            flash(f"Invalid credentials ({user.failed_attempts}/5)", "error")

        db.session.commit()

    return render_template('login.html')

@app.route('/folder/<string:folder_uuid>')
def view_folder(folder_uuid):
    if "user_id" not in session:
        return redirect(url_for("login"))

    folder = Folder.query.filter_by(uuid=folder_uuid, user_id=session['user_id']).first()

    if not folder or folder.user_id != session['user_id']:
        abort(403)

    files = File.query.filter_by(folder_uuid=folder_uuid).all()

    return render_template("folder.html", folder=folder, files=files)

@app.route('/delete_file/<int:file_id>')
def delete_file(file_id):
    if "user_id" not in session:
        return redirect(url_for("login"))

    file = File.query.get(file_id)

    if not file or file.user_id != session['user_id']:
        abort(403)

    path = os.path.join(
        app.config['UPLOAD_FOLDER'],
        f"user_{session['user_id']}",
        f"folder_{file.folder_uuid}",
        file.filename
    )

    if os.path.exists(path):
        os.remove(path)

    db.session.delete(file)
    db.session.commit()

    flash("File deleted", "success")
    return redirect(request.referrer or url_for('dashboard'))

@app.route('/signup', methods=['GET', 'POST'])
@limiter.limit("10 per minute")
def signup():
    if request.method == "POST":
        name = request.form['name']
        email = request.form['email']
        password = request.form['password']

        if len(password) >= 8:
            if User.query.filter_by(email=email).first():
                flash("User already exists", "error")
                return render_template('signup.html')

            hashed_password = generate_password_hash(password, method='pbkdf2:sha256', salt_length=16)

            new_user = User(
                name=name,
                email=email,
                password=hashed_password
            )

            db.session.add(new_user)
            db.session.commit()

            flash("Account created!", "success")
            return redirect(url_for('login'))
        else:
            flash("Password must be at least 8 characters", "error")

    return render_template('signup.html')


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/about')
def about():
    return render_template('about.html')


@app.route('/profile')
def profile():
    if "user_id" not in session:
        return redirect(url_for("login"))
    return render_template('profile.html')


@app.route('/settings')
def settings():
    if "user_id" not in session:
        return redirect(url_for("login"))
    return render_template('settings.html')
    
@app.route('/rename_file/<int:file_id>', methods=['POST'])
def rename_file(file_id):
    if "user_id" not in session:
        return redirect(url_for("login"))

    file = File.query.get(file_id)

    if not file or file.user_id != session['user_id']:
        abort(403)

    new_name = request.form.get("new_name")

    if new_name:
        new_name = secure_filename(new_name)
        
        # Validate extension
        if not allowed_file(new_name):
            flash("File extension not allowed", "error")
            return redirect(request.referrer or url_for('dashboard'))

        old_path = os.path.join(
            app.config['UPLOAD_FOLDER'],
            f"user_{session['user_id']}",
            f"folder_{file.folder_uuid}",  # Use folder_uuid for consistency
            file.filename
        )

        new_path = os.path.join(
            app.config['UPLOAD_FOLDER'],
            f"user_{session['user_id']}",
            f"folder_{file.folder_uuid}",
            new_name
        )

        try:
            if os.path.exists(old_path):
                os.rename(old_path, new_path)
            
            file.filename = new_name
            db.session.commit()
            flash("File renamed successfully", "success")
        except Exception as e:
            db.session.rollback()
            flash("Failed to rename file", "error")

    return redirect(request.referrer or url_for('dashboard'))

@app.route('/view/<int:file_id>')
def view_file(file_id):
    if "user_id" not in session:
        return redirect(url_for("login"))

    file = File.query.get(file_id)

    if not file or file.user_id != session['user_id']:
        abort(403)

    folder_path = os.path.join(
        app.config['UPLOAD_FOLDER'],
        f"user_{session['user_id']}",
        f"folder_{file.folder_uuid}"
    )

    if not os.path.exists(os.path.join(folder_path, file.filename)):
        flash("File not found", "error")
        return redirect(request.referrer or url_for('dashboard'))
    return send_from_directory(folder_path, file.filename)

@app.route('/update_name', methods=['POST'])
def update_name():
    if "user_id" not in session:
        flash("Unauthorized", "error")
        return redirect(url_for('settings'))

    user = User.query.get(session['user_id'])
    new_name = request.form['new_name']

    if not new_name:
        flash("Name cannot be empty", "error")
        return redirect(url_for('settings'))

    user.name = new_name
    session['user'] = new_name

    db.session.commit()
    flash("Name updated successfully", "success")
    return redirect(url_for('settings'))

@app.route('/change_password', methods=['POST'])
def change_password():
    if "user_id" not in session:
        flash("Unauthorized", "error")
        return redirect(url_for('settings'))

    user = User.query.get(session['user_id'])
    old = request.form['old_password']
    new = request.form['new_password']

    if not check_password_hash(user.password, old):
        flash("Old password is incorrect", "error")
        return redirect(url_for('settings'))

    user.password = generate_password_hash(new)
    db.session.commit()

    flash("Password changed successfully", "success")
    return redirect(url_for('settings'))

@app.route('/delete_account', methods=['POST'])
@limiter.limit("5 per hour")
def delete_account():
    if "user_id" not in session:
        flash("Unauthorized", "error")
        return redirect(url_for('settings'))

    user = User.query.get(session['user_id'])
    password = request.form.get('password', '')

    # Verify password before deletion
    if not check_password_hash(user.password, password):
        flash("Incorrect password. Account not deleted.", "error")
        return redirect(url_for('settings'))

    # Delete user's files and folders from disk
    user_folder = os.path.join(
        app.config['UPLOAD_FOLDER'],
        f"user_{session['user_id']}"
    )
    
    if os.path.exists(user_folder):
        shutil.rmtree(user_folder)

    # Delete database records
    File.query.filter_by(user_id=session['user_id']).delete()
    Folder.query.filter_by(user_id=session['user_id']).delete()
    db.session.delete(user)
    db.session.commit()

    session.clear()
    flash("Account deleted successfully", "success")
    return redirect(url_for('home'))

@app.route('/delete_folder/<string:folder_uuid>', methods=['POST'])
def delete_folder(folder_uuid):
    print("DELETE ROUTE HIT:", folder_uuid)
    if "user_id" not in session:
        return redirect(url_for("login"))

    folder = Folder.query.filter_by(uuid=folder_uuid, user_id=session['user_id']).first()

    if not folder:
        abort(403)

    folder_path = os.path.join(
        app.config['UPLOAD_FOLDER'],
        f"user_{session['user_id']}",
        f"folder_{folder_uuid}"
    )

    if os.path.exists(folder_path):
        for filename in os.listdir(folder_path):
            file_path = os.path.join(folder_path, filename)
            if os.path.isfile(file_path):
                os.remove(file_path)

        # remove folder itself
        os.rmdir(folder_path)

    File.query.filter_by(folder_uuid=folder_uuid).delete()

    db.session.delete(folder)
    db.session.commit()

    flash("Folder deleted successfully", "success")

    return redirect(url_for('dashboard'))

@app.route('/download/<int:file_id>')
@app.route('/download/<int:file_id>')
def download_file(file_id):
    if "user_id" not in session:
        return redirect(url_for("login"))

    file = File.query.get(file_id)

    if not file or file.user_id != session['user_id']:
        abort(403)

    folder_path = os.path.join(
        app.config['UPLOAD_FOLDER'],
        f"user_{session['user_id']}",
        f"folder_{file.folder_uuid}"
    )

    if not os.path.exists(os.path.join(folder_path, file.filename)):
        flash("File not found", "error")
        return redirect(request.referrer or url_for('dashboard'))
    return send_from_directory(folder_path, file.filename, as_attachment=True)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
    