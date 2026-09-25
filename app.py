import os
from functools import wraps
from pathlib import Path

import pymysql
from flask import (
    Flask,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_from_directory,
    session,
    url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

BASE_DIR = Path(__file__).resolve().parent
UPLOAD_FOLDER = BASE_DIR / os.getenv("UPLOAD_FOLDER", "uploads")
UPLOAD_FOLDER.mkdir(parents=True, exist_ok=True)

app = Flask(__name__)
app.config.update(
    SECRET_KEY=os.getenv("SECRET_KEY", "change-this-development-secret"),
    UPLOAD_FOLDER=str(UPLOAD_FOLDER),
)


def get_db_connection():
    return pymysql.connect(
        host=os.getenv("DB_HOST", "127.0.0.1"),
        port=int(os.getenv("DB_PORT", "3306")),
        user=os.getenv("DB_USER", "music_app"),
        password=os.getenv("DB_PASSWORD", ""),
        database=os.getenv("DB_NAME", "music_app"),
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=False,
    )


def login_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if "user_id" not in session:
            flash("Please log in to continue.", "info")
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)

    return wrapped_view


@app.context_processor
def inject_current_user():
    return {"current_username": session.get("username")}


@app.get("/")
def index():
    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT s.id, s.title, s.artist, s.filepath, s.uploaded_at,
                       u.username AS uploader,
                       COALESCE(AVG(r.stars), 0) AS avg_rating,
                       COUNT(r.id) AS rating_count
                FROM songs s
                JOIN users u ON u.id = s.uploader_id
                LEFT JOIN ratings r ON r.song_id = s.id
                GROUP BY s.id, s.title, s.artist, s.filepath, s.uploaded_at, u.username
                ORDER BY s.uploaded_at DESC, s.id DESC
                """
            )
            songs = cursor.fetchall()
    finally:
        connection.close()
    return render_template("index.html", songs=songs)


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        if not username or not password:
            flash("Username and password are required.", "error")
            return render_template("register.html")
        if len(username) > 50:
            flash("Username must be 50 characters or fewer.", "error")
            return render_template("register.html")

        connection = get_db_connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO users (username, password_hash) VALUES (%s, %s)",
                    (username, generate_password_hash(password)),
                )
            connection.commit()
        except pymysql.err.IntegrityError:
            connection.rollback()
            flash("That username is already taken.", "error")
            return render_template("register.html")
        finally:
            connection.close()
        flash("Account created. You can now log in.", "success")
        return redirect(url_for("login"))
    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        connection = get_db_connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT id, username, password_hash FROM users WHERE username = %s", (username,))
                user = cursor.fetchone()
        finally:
            connection.close()
        if user and check_password_hash(user["password_hash"], password):
            session.clear()
            session["user_id"] = user["id"]
            session["username"] = user["username"]
            return redirect(request.args.get("next") or url_for("index"))
        flash("Invalid username or password.", "error")
    return render_template("login.html")


@app.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))


@app.route("/upload", methods=["GET", "POST"])
@login_required
def upload():
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        artist = request.form.get("artist", "").strip()
        audio_file = request.files.get("audio_file")
        if not title or not artist or not audio_file or not audio_file.filename:
            flash("Title, artist, and an audio file are required.", "error")
            return render_template("upload.html")

        safe_name = secure_filename(audio_file.filename)
        if not safe_name:
            flash("Please choose a valid filename.", "error")
            return render_template("upload.html")
        stored_name = f"{session['user_id']}_{os.urandom(8).hex()}_{safe_name}"
        audio_file.save(UPLOAD_FOLDER / stored_name)

        connection = get_db_connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO songs (uploader_id, title, artist, filepath) VALUES (%s, %s, %s, %s)",
                    (session["user_id"], title, artist, stored_name),
                )
            connection.commit()
        finally:
            connection.close()
        flash("Your song is now in the library.", "success")
        return redirect(url_for("index"))
    return render_template("upload.html")


@app.get("/media/<path:filename>")
def media(filename):
    return send_from_directory(app.config["UPLOAD_FOLDER"], filename)


@app.post("/songs/<int:song_id>/rating")
@login_required
def rate_song(song_id):
    payload = request.get_json(silent=True) or request.form
    try:
        stars = int(payload.get("stars", 0))
    except (TypeError, ValueError):
        stars = 0
    review_text = (payload.get("review_text") or "").strip() or None
    if stars not in range(1, 6):
        return jsonify(error="Rating must be between 1 and 5."), 400

    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT id FROM songs WHERE id = %s", (song_id,))
            if cursor.fetchone() is None:
                return jsonify(error="Song not found."), 404
            cursor.execute(
                """
                INSERT INTO ratings (song_id, user_id, stars, review_text)
                VALUES (%s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE stars = VALUES(stars), review_text = VALUES(review_text)
                """,
                (song_id, session["user_id"], stars, review_text),
            )
            cursor.execute(
                "SELECT COALESCE(AVG(stars), 0) AS avg_rating, COUNT(*) AS rating_count FROM ratings WHERE song_id = %s",
                (song_id,),
            )
            summary = cursor.fetchone()
        connection.commit()
    finally:
        connection.close()
    return jsonify(avg_rating=float(summary["avg_rating"]), rating_count=summary["rating_count"])


if __name__ == "__main__":
    app.run(debug=os.getenv("FLASK_DEBUG", "0") == "1")
