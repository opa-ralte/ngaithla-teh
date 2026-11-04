import os
import secrets
from functools import wraps
from pathlib import Path

import pymysql
import click
from flask import (
    Flask,
    abort,
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


def admin_required(view):
    @wraps(view)
    @login_required
    def wrapped_view(*args, **kwargs):
        connection = get_db_connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT is_admin FROM users WHERE id = %s", (session["user_id"],))
                user = cursor.fetchone()
        finally:
            connection.close()
        if not user or not user["is_admin"]:
            abort(403)
        session["is_admin"] = True
        return view(*args, **kwargs)

    return wrapped_view


def csrf_token():
    token = session.get("_csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["_csrf_token"] = token
    return token


def validate_csrf():
    token = request.form.get("_csrf_token", "")
    if not token or not secrets.compare_digest(token, session.get("_csrf_token", "")):
        abort(400, description="Invalid or missing CSRF token.")


def pagination(page_value, per_page=20):
    try:
        page = max(1, int(page_value))
    except (TypeError, ValueError):
        page = 1
    return page, per_page, (page - 1) * per_page


@app.context_processor
def inject_current_user():
    return {
        "current_username": session.get("username"),
        "current_is_admin": session.get("is_admin", False),
        "csrf_token": csrf_token,
    }


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
                cursor.execute(
                    "SELECT id, username, password_hash, is_admin FROM users WHERE username = %s",
                    (username,),
                )
                user = cursor.fetchone()
        finally:
            connection.close()
        if user and check_password_hash(user["password_hash"], password):
            session.clear()
            session["user_id"] = user["id"]
            session["username"] = user["username"]
            session["is_admin"] = bool(user["is_admin"])
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


@app.cli.command("create-admin")
def create_admin():
    """Create an administrator account or promote an existing user."""
    username = click.prompt("Username").strip()
    password = click.prompt("Password", hide_input=True, confirmation_prompt=True)
    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT id, is_admin FROM users WHERE username = %s", (username,))
            user = cursor.fetchone()
            if user:
                if user["is_admin"]:
                    raise click.ClickException("That user is already an administrator.")
                cursor.execute("UPDATE users SET is_admin = 1 WHERE id = %s", (user["id"],))
            else:
                cursor.execute(
                    "INSERT INTO users (username, password_hash, is_admin) VALUES (%s, %s, 1)",
                    (username, generate_password_hash(password)),
                )
        connection.commit()
    except pymysql.err.IntegrityError as error:
        connection.rollback()
        raise click.ClickException("Could not create the administrator.") from error
    finally:
        connection.close()
    click.echo("Administrator account is ready.")


@app.get("/admin")
@admin_required
def admin_dashboard():
    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    (SELECT COUNT(*) FROM users) AS user_count,
                    (SELECT COUNT(*) FROM songs) AS song_count,
                    (SELECT COUNT(*) FROM ratings) AS rating_count,
                    (SELECT COALESCE(AVG(stars), 0) FROM ratings) AS average_rating,
                    (SELECT COUNT(*) FROM users WHERE is_admin = 1) AS admin_count
                """
            )
            stats = cursor.fetchone()
            cursor.execute("SELECT username, created_at FROM users ORDER BY created_at DESC, id DESC LIMIT 5")
            recent_users = cursor.fetchall()
            cursor.execute(
                """
                SELECT s.title, s.artist, u.username AS uploader, s.uploaded_at
                FROM songs s JOIN users u ON u.id = s.uploader_id
                ORDER BY s.uploaded_at DESC, s.id DESC LIMIT 5
                """
            )
            recent_songs = cursor.fetchall()
            cursor.execute(
                """
                SELECT r.stars, r.review_text, r.created_at, s.title AS song_title, u.username
                FROM ratings r JOIN songs s ON s.id = r.song_id JOIN users u ON u.id = r.user_id
                ORDER BY r.created_at DESC, r.id DESC LIMIT 5
                """
            )
            recent_ratings = cursor.fetchall()
    finally:
        connection.close()
    return render_template(
        "admin/dashboard.html",
        stats=stats,
        recent_users=recent_users,
        recent_songs=recent_songs,
        recent_ratings=recent_ratings,
    )


@app.get("/admin/songs")
@admin_required
def admin_songs():
    page, per_page, offset = pagination(request.args.get("page"))
    search = request.args.get("q", "").strip()
    term = f"%{search}%"
    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT COUNT(*) AS total
                FROM songs s JOIN users u ON u.id = s.uploader_id
                WHERE (%s = '' OR s.title LIKE %s OR s.artist LIKE %s OR u.username LIKE %s)
                """,
                (search, term, term, term),
            )
            total = cursor.fetchone()["total"]
            cursor.execute(
                """
                SELECT s.id, s.title, s.artist, s.filepath, s.uploaded_at,
                       u.username AS uploader, COALESCE(AVG(r.stars), 0) AS avg_rating,
                       COUNT(r.id) AS rating_count
                FROM songs s JOIN users u ON u.id = s.uploader_id
                LEFT JOIN ratings r ON r.song_id = s.id
                WHERE (%s = '' OR s.title LIKE %s OR s.artist LIKE %s OR u.username LIKE %s)
                GROUP BY s.id, s.title, s.artist, s.filepath, s.uploaded_at, u.username
                ORDER BY s.uploaded_at DESC, s.id DESC
                LIMIT %s OFFSET %s
                """,
                (search, term, term, term, per_page, offset),
            )
            songs = cursor.fetchall()
    finally:
        connection.close()
    return render_template(
        "admin/songs.html", songs=songs, page=page, per_page=per_page, total=total, search=search
    )


@app.post("/admin/songs/<int:song_id>/delete")
@admin_required
def admin_delete_song(song_id):
    validate_csrf()
    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT filepath FROM songs WHERE id = %s", (song_id,))
            song = cursor.fetchone()
            if not song:
                flash("Song not found.", "error")
                return redirect(url_for("admin_songs"))
            filepath = song["filepath"]
            cursor.execute("DELETE FROM songs WHERE id = %s", (song_id,))
        connection.commit()
    finally:
        connection.close()
    media_path = (Path(app.config["UPLOAD_FOLDER"]) / filepath).resolve()
    upload_root = Path(app.config["UPLOAD_FOLDER"]).resolve()
    if upload_root == media_path.parent or upload_root in media_path.parents:
        if media_path.is_file():
            media_path.unlink()
    flash("Song deleted.", "success")
    return redirect(url_for("admin_songs"))


@app.get("/admin/users")
@admin_required
def admin_users():
    page, per_page, offset = pagination(request.args.get("page"))
    search = request.args.get("q", "").strip()
    term = f"%{search}%"
    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT COUNT(*) AS total FROM users WHERE (%s = '' OR username LIKE %s)",
                (search, term),
            )
            total = cursor.fetchone()["total"]
            cursor.execute(
                """
                SELECT u.id, u.username, u.is_admin, u.created_at,
                       COUNT(DISTINCT s.id) AS song_count, COUNT(DISTINCT r.id) AS rating_count
                FROM users u
                LEFT JOIN songs s ON s.uploader_id = u.id
                LEFT JOIN ratings r ON r.user_id = u.id
                WHERE (%s = '' OR u.username LIKE %s)
                GROUP BY u.id, u.username, u.is_admin, u.created_at
                ORDER BY u.created_at DESC, u.id DESC
                LIMIT %s OFFSET %s
                """,
                (search, term, per_page, offset),
            )
            users = cursor.fetchall()
    finally:
        connection.close()
    return render_template(
        "admin/users.html", users=users, page=page, per_page=per_page, total=total, search=search
    )


@app.post("/admin/users/<int:user_id>/toggle-admin")
@admin_required
def admin_toggle_user(user_id):
    validate_csrf()
    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT id, is_admin FROM users WHERE id = %s", (user_id,))
            user = cursor.fetchone()
            if not user:
                flash("User not found.", "error")
                return redirect(url_for("admin_users"))
            if user["is_admin"] and user["id"] == session["user_id"]:
                cursor.execute("SELECT COUNT(*) AS total FROM users WHERE is_admin = 1")
                if cursor.fetchone()["total"] <= 1:
                    flash("You cannot remove the last administrator.", "error")
                    return redirect(url_for("admin_users"))
            cursor.execute("UPDATE users SET is_admin = NOT is_admin WHERE id = %s", (user_id,))
        connection.commit()
    finally:
        connection.close()
    if user_id == session["user_id"]:
        session["is_admin"] = not user["is_admin"]
    flash("Administrator status updated.", "success")
    return redirect(url_for("admin_users"))


@app.post("/admin/users/<int:user_id>/delete")
@admin_required
def admin_delete_user(user_id):
    validate_csrf()
    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT id, is_admin FROM users WHERE id = %s", (user_id,))
            user = cursor.fetchone()
            if not user:
                flash("User not found.", "error")
                return redirect(url_for("admin_users"))
            if user["is_admin"]:
                cursor.execute("SELECT COUNT(*) AS total FROM users WHERE is_admin = 1")
                if cursor.fetchone()["total"] <= 1:
                    flash("The last administrator cannot be deleted.", "error")
                    return redirect(url_for("admin_users"))
            cursor.execute("DELETE FROM users WHERE id = %s", (user_id,))
        connection.commit()
    finally:
        connection.close()
    flash("User deleted along with their songs and ratings.", "success")
    return redirect(url_for("admin_users"))


@app.get("/admin/ratings")
@admin_required
def admin_ratings():
    page, per_page, offset = pagination(request.args.get("page"))
    search = request.args.get("q", "").strip()
    term = f"%{search}%"
    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT COUNT(*) AS total
                FROM ratings r JOIN songs s ON s.id = r.song_id JOIN users u ON u.id = r.user_id
                WHERE (%s = '' OR s.title LIKE %s OR u.username LIKE %s OR r.review_text LIKE %s)
                """,
                (search, term, term, term),
            )
            total = cursor.fetchone()["total"]
            cursor.execute(
                """
                SELECT r.id, r.stars, r.review_text, r.created_at,
                       s.title AS song_title, u.username
                FROM ratings r JOIN songs s ON s.id = r.song_id JOIN users u ON u.id = r.user_id
                WHERE (%s = '' OR s.title LIKE %s OR u.username LIKE %s OR r.review_text LIKE %s)
                ORDER BY r.created_at DESC, r.id DESC LIMIT %s OFFSET %s
                """,
                (search, term, term, term, per_page, offset),
            )
            ratings = cursor.fetchall()
    finally:
        connection.close()
    return render_template(
        "admin/ratings.html", ratings=ratings, page=page, per_page=per_page, total=total, search=search
    )


@app.post("/admin/ratings/<int:rating_id>/delete")
@admin_required
def admin_delete_rating(rating_id):
    validate_csrf()
    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM ratings WHERE id = %s", (rating_id,))
            deleted = cursor.rowcount
        connection.commit()
    finally:
        connection.close()
    flash("Rating deleted." if deleted else "Rating not found.", "success" if deleted else "error")
    return redirect(url_for("admin_ratings"))


if __name__ == "__main__":
    app.run(debug=os.getenv("FLASK_DEBUG", "0") == "1")
