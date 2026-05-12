from flask import Flask, render_template, redirect, url_for, session, request, flash, abort
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta
from flask_limiter import Limiter
from supabase import create_client
from flask_limiter.util import get_remote_address
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from flask_wtf.csrf import CSRFProtect
from dotenv import load_dotenv
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

# Database config
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get("DATABASE_URL")
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
    "pool_pre_ping": True
}
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Upload config
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024

# Supabase config
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# Session security
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SECURE=True,
    SESSION_COOKIE_SAMESITE="Lax"
)

app.permanent_session_lifetime = timedelta(days=30)

db = SQLAlchemy(app)
with app.app_context():
    db.create_all()
# Models
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)

    email = db.Column(db.String(100), unique=True, nullable=False)

    password = db.Column(db.String(200), nullable=False)

    failed_attempts = db.Column(db.Integer, default=0)

    locked_until = db.Column(db.DateTime, nullable=True)


class Folder(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    uuid = db.Column(
        db.String(36),
        unique=True,
        default=lambda: str(uuid.uuid4())
    )

    name = db.Column(db.String(100))

    user_id = db.Column(
        db.Integer,
        db.ForeignKey('user.id'),
        nullable=False
    )


class File(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    filename = db.Column(db.String(200))

    file_url = db.Column(db.String(500))

    user_id = db.Column(
        db.Integer,
        db.ForeignKey('user.id'),
        nullable=False
    )

    folder_id = db.Column(
        db.Integer,
        db.ForeignKey('folder.id'),
        nullable=False
    )

    folder_uuid = db.Column(db.String(36), nullable=False)


ALLOWED_EXTENSIONS = {
    'pdf',
    'txt',
    'png',
    'jpg',
    'jpeg',
    'webp',
    'gif',
    'docx',
    'xlsx',
    'pptx',
    'mp4',
    'webm',
    'mov',
    'mp3',
    'wav',
    'zip'
}


def allowed_file(filename):
    return (
        '.' in filename and
        filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS
    )


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

    folders = Folder.query.filter_by(
        user_id=session['user_id']
    ).all()

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

    folder = Folder.query.filter_by(
        uuid=folder_uuid,
        user_id=session['user_id']
    ).first()

    if not folder:
        abort(403)

    return render_template("upload.html", folder=folder)


@app.route('/upload/<string:folder_uuid>', methods=['POST'])
def upload_file(folder_uuid):
    if "user_id" not in session:
        return redirect(url_for('login'))

    folder = Folder.query.filter_by(
        uuid=folder_uuid,
        user_id=session['user_id']
    ).first()

    if not folder:
        abort(403)

    file = request.files.get('file')

    if file and file.filename != "" and allowed_file(file.filename):

        filename = secure_filename(file.filename)

        unique_name = f"{uuid.uuid4()}_{filename}"

        file_path = f"{folder_uuid}/{unique_name}"

        file_data = file.read()

        supabase.storage.from_("uploads").upload(
            file_path,
            file_data
        )

        new_file = File(
            filename=unique_name,
            file_url=file_path,
            user_id=session['user_id'],
            folder_id=folder.id,
            folder_uuid=folder.uuid
        )

        db.session.add(new_file)
        db.session.commit()

        flash("File uploaded!", "success")

    else:
        flash("File extension not allowed!", "error")

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

        if (
            user.locked_until and
            datetime.utcnow() < user.locked_until
        ):
            flash("Account locked. Try again later.", "error")
            return redirect(url_for('login'))

        if check_password_hash(user.password, password):

            user.failed_attempts = 0
            user.locked_until = None

            session.permanent = True

            session['user_id'] = user.id
            session['user'] = user.name
            session['email'] = user.email

            db.session.commit()

            return redirect(url_for('dashboard'))

        user.failed_attempts += 1

        if user.failed_attempts >= 5:

            user.locked_until = (
                datetime.utcnow() + timedelta(minutes=10)
            )

            flash(
                "Too many attempts. Locked for 10 minutes.",
                "error"
            )

        else:
            flash(
                f"Invalid credentials ({user.failed_attempts}/5)",
                "error"
            )

        db.session.commit()

    return render_template('login.html')


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

            hashed_password = generate_password_hash(
                password,
                method='pbkdf2:sha256',
                salt_length=16
            )

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
            flash(
                "Password must be at least 8 characters",
                "error"
            )

    return render_template('signup.html')


@app.route('/folder/<string:folder_uuid>')
def view_folder(folder_uuid):

    if "user_id" not in session:
        return redirect(url_for("login"))

    folder = Folder.query.filter_by(
        uuid=folder_uuid,
        user_id=session['user_id']
    ).first()

    if not folder:
        abort(403)

    files = File.query.filter_by(
        folder_uuid=folder_uuid
    ).all()

    return render_template(
        "folder.html",
        folder=folder,
        files=files
    )


@app.route('/view/<int:file_id>')
def view_file(file_id):

    if "user_id" not in session:
        return redirect(url_for("login"))

    file = File.query.get(file_id)

    if not file or file.user_id != session['user_id']:
        abort(403)

    signed_url = supabase.storage.from_(
        "uploads"
    ).create_signed_url(
        file.file_url,
        3600
    )

    return redirect(signed_url["signedURL"])


@app.route('/download/<int:file_id>')
def download_file(file_id):

    if "user_id" not in session:
        return redirect(url_for("login"))

    file = File.query.get(file_id)

    if not file or file.user_id != session['user_id']:
        abort(403)

    signed_url = supabase.storage.from_(
        "uploads"
    ).create_signed_url(
        file.file_url,
        3600
    )

    return redirect(signed_url["signedURL"])


@app.route('/delete_file/<int:file_id>')
def delete_file(file_id):

    if "user_id" not in session:
        return redirect(url_for("login"))

    file = File.query.get(file_id)

    if not file or file.user_id != session['user_id']:
        abort(403)

    supabase.storage.from_("uploads").remove(
        [file.file_url]
    )

    db.session.delete(file)
    db.session.commit()

    flash("File deleted", "success")

    return redirect(
        request.referrer or url_for('dashboard')
    )


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

    flash(
        "Rename feature temporarily disabled",
        "error"
    )

    return redirect(
        request.referrer or url_for('dashboard')
    )


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

    flash(
        "Password changed successfully",
        "success"
    )

    return redirect(url_for('settings'))


@app.route('/delete_account', methods=['POST'])
@limiter.limit("5 per hour")
def delete_account():

    if "user_id" not in session:

        flash("Unauthorized", "error")

        return redirect(url_for('settings'))

    user = User.query.get(session['user_id'])

    password = request.form.get('password', '')

    if not check_password_hash(user.password, password):

        flash(
            "Incorrect password. Account not deleted.",
            "error"
        )

        return redirect(url_for('settings'))

    files = File.query.filter_by(
        user_id=session['user_id']
    ).all()

    for file in files:
        supabase.storage.from_("uploads").remove(
            [file.file_url]
        )

    File.query.filter_by(
        user_id=session['user_id']
    ).delete()

    Folder.query.filter_by(
        user_id=session['user_id']
    ).delete()

    db.session.delete(user)

    db.session.commit()

    session.clear()

    flash(
        "Account deleted successfully",
        "success"
    )

    return redirect(url_for('home'))


@app.route('/delete_folder/<string:folder_uuid>', methods=['POST'])
def delete_folder(folder_uuid):

    if "user_id" not in session:
        return redirect(url_for("login"))

    folder = Folder.query.filter_by(
        uuid=folder_uuid,
        user_id=session['user_id']
    ).first()

    if not folder:
        abort(403)

    files = File.query.filter_by(
        folder_uuid=folder_uuid
    ).all()

    for file in files:
        supabase.storage.from_("uploads").remove(
            [file.file_url]
        )

    File.query.filter_by(
        folder_uuid=folder_uuid
    ).delete()

    db.session.delete(folder)

    db.session.commit()

    flash(
        "Folder deleted successfully",
        "success"
    )

    return redirect(url_for('dashboard'))


if __name__ == "__main__":
    app.run()