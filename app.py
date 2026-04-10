from flask import Flask, render_template, redirect, url_for, session, request, flash
from datetime import timedelta
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import secrets
import os

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", secrets.token_hex(16))

# DB config
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get(
    "DATABASE_URL",
    "sqlite:///users.sqlite3"
)
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Upload config
app.config['UPLOAD_FOLDER'] = 'uploads'

app.permanent_session_lifetime = timedelta(days=30)

db = SQLAlchemy(app)

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)


class Folder(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100))
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)


class File(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(200))
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    folder_id = db.Column(db.Integer, db.ForeignKey('folder.id'), nullable=False)

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

@app.route('/upload_page/<int:folder_id>')
def upload_page(folder_id):
    if "user_id" not in session:
        return redirect(url_for("login"))

    folder = Folder.query.get(folder_id)

    if not folder or folder.user_id != session['user_id']:
        return "Unauthorized", 403

    return render_template("upload.html", folder=folder)


@app.route('/upload/<int:folder_id>', methods=['POST'])
def upload_file(folder_id):
    if "user_id" not in session:
        return redirect(url_for('login'))

    folder = Folder.query.get(folder_id)

    if not folder or folder.user_id != session['user_id']:
        return "Unauthorized", 403

    file = request.files.get('file')

    if file and file.filename != "":
        filename = secure_filename(file.filename)

        user_folder = os.path.join(
            app.config['UPLOAD_FOLDER'],
            f"user_{session['user_id']}",
            f"folder_{folder_id}"
        )

        os.makedirs(user_folder, exist_ok=True)

        filepath = os.path.join(user_folder, filename)
        file.save(filepath)

        new_file = File(
            filename=filename,
            user_id=session['user_id'],
            folder_id=folder_id
        )

        db.session.add(new_file)
        db.session.commit()

        flash("File uploaded!", "success")

    return redirect(url_for('dashboard'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if "user_id" in session:
        return redirect(url_for('dashboard'))

    if request.method == "POST":
        email = request.form['email']
        password = request.form['password']

        user = User.query.filter_by(email=email).first()

        if user and check_password_hash(user.password, password):
            session['user_id'] = user.id
            session['user'] = user.name
            session['email'] = user.email
            return redirect(url_for('dashboard'))
        
        flash("Invalid credentials", "error")

    return render_template('login.html')

@app.route('/folder/<int:folder_id>')
def view_folder(folder_id):
    if "user_id" not in session:
        return redirect(url_for("login"))

    folder = Folder.query.get(folder_id)

    if not folder or folder.user_id != session['user_id']:
        return "Unauthorized", 403

    files = File.query.filter_by(folder_id=folder_id).all()

    return render_template("folder.html", folder=folder, files=files)

@app.route('/delete_file/<int:file_id>')
def delete_file(file_id):
    if "user_id" not in session:
        return redirect(url_for("login"))

    file = File.query.get(file_id)

    if not file or file.user_id != session['user_id']:
        return "Unauthorized", 403

    path = os.path.join(
        app.config['UPLOAD_FOLDER'],
        f"user_{session['user_id']}",
        f"folder_{file.folder_id}",
        file.filename
    )

    if os.path.exists(path):
        os.remove(path)

    db.session.delete(file)
    db.session.commit()

    flash("File deleted", "success")
    return redirect(request.referrer)


@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == "POST":
        name = request.form['name']
        email = request.form['email']
        password = request.form['password']

        if User.query.filter_by(email=email).first():
            flash("User already exists", "error")
            return render_template('signup.html')

        hashed_password = generate_password_hash(password)

        new_user = User(
            name=name,
            email=email,
            password=hashed_password
        )

        db.session.add(new_user)
        db.session.commit()

        flash("Account created!", "success")
        return redirect(url_for('login'))

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

if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    os.makedirs("uploads", exist_ok=True)
    app.run(debug=True)
    
