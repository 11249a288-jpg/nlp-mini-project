import os
import re
import csv
import io
import sqlite3
from datetime import datetime
from functools import wraps

from flask import (
    Flask, request, redirect, url_for,
    session, flash, render_template,
    make_response
)
from werkzeug.security import generate_password_hash, check_password_hash

# Resolve the directory where this file lives so that
# templates and the database are always found regardless
# of the working directory (required for Vercel serverless).
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = Flask(__name__, template_folder=os.path.join(BASE_DIR, "templates"))
app.secret_key = os.environ.get("SECRET_KEY", "campus_analyzer_secret_2026")

# Vercel's filesystem is read-only except for /tmp.
# Locally we keep the DB next to app.py for convenience.
DB = (
    "/tmp/campus_analyzer.db"
    if os.environ.get("VERCEL")
    else os.path.join(BASE_DIR, "campus_analyzer.db")
)


# ---------------- DATABASE ----------------

def init_db():
    with sqlite3.connect(DB) as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id       INTEGER PRIMARY KEY AUTOINCREMENT,
                name     TEXT NOT NULL,
                email    TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL
            )
        """)

        con.execute("""
            CREATE TABLE IF NOT EXISTS feedback (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id    INTEGER,
                message    TEXT,
                category   TEXT,
                sentiment  TEXT,
                score      INTEGER,
                keywords   TEXT,
                created_at TEXT
            )
        """)

        con.commit()


# ---------------- NLP WORD LISTS ----------------

STOP_WORDS = {
    "the", "is", "are", "a", "an", "and", "or",
    "to", "of", "in", "on", "for", "this", "that",
    "it", "was", "were", "with", "we", "our",
    "my", "they", "their", "be", "am", "very"
}

POSITIVE_WORDS = {
    "good", "great", "excellent", "helpful",
    "clean", "nice", "comfortable", "better",
    "best", "amazing", "available", "timely",
    "safe", "friendly", "improved", "love",
    "working", "correct"
}

NEGATIVE_WORDS = {
    "bad", "poor", "dirty", "unclean", "late",
    "delay", "delayed", "broken", "worst",
    "terrible", "problem", "issue", "unsafe",
    "slow", "damaged", "waste", "unhygienic",
    "missing", "overcrowded"
}

NEGATIONS = {
    "not", "no", "never", "isn't", "aren't",
    "wasn't", "weren't", "don't", "doesn't"
}

# Merge negation words into stop-words so they are
# excluded from keyword output
STOP_WORDS = STOP_WORDS | NEGATIONS

CATEGORIES = {
    "Classroom / Cleanliness": [
        "classroom", "class", "room", "bench",
        "desk", "clean", "cleanliness", "fan",
        "light", "projector"
    ],
    "Bus / Transport": [
        "bus", "transport", "driver", "route",
        "stop", "travel", "vehicle", "timing"
    ],
    "Library": [
        "library", "book", "books", "reading",
        "librarian", "journal"
    ],
    "Canteen": [
        "canteen", "food", "meal", "snack",
        "water", "menu", "price"
    ],
    "Campus Facilities": [
        "campus", "wifi", "internet", "washroom",
        "toilet", "parking", "playground",
        "facility", "facilities"
    ]
}


# ---------------- NLP ANALYSIS ----------------

def analyze_feedback(message):

    tokens = re.findall(r"[a-zA-Z']+", message.lower())

    # Category identification
    category = "Campus Facilities"

    for name, words in CATEGORIES.items():
        if any(word in tokens for word in words):
            category = name
            break

    # Sentiment analysis
    score = 0

    for i, word in enumerate(tokens):

        if word in POSITIVE_WORDS:
            change = 1

        elif word in NEGATIVE_WORDS:
            change = -1

        else:
            continue

        # Negation handling — check the word immediately before
        if i > 0 and tokens[i - 1] in NEGATIONS:
            change *= -1

        score += change

    if score > 0:
        sentiment = "Positive"
    elif score < 0:
        sentiment = "Negative"
    else:
        sentiment = "Neutral"

    # Stop-word removal and keyword extraction
    keywords = [
        word for word in tokens
        if word not in STOP_WORDS and len(word) > 2
    ]

    keywords = ", ".join(keywords[:12])

    return category, sentiment, score, keywords


# ---------------- LOGIN PROTECTION ----------------

def login_required(function):

    @wraps(function)
    def wrapper(*args, **kwargs):

        if "user_id" not in session:
            return redirect(url_for("login"))

        return function(*args, **kwargs)

    return wrapper


# ---------------- HOME PAGE ----------------

@app.route("/")
def home():
    return render_template("home.html")


# ---------------- SIGN UP ----------------

@app.route("/signup", methods=["GET", "POST"])
def signup():

    if request.method == "POST":

        name     = request.form["name"].strip()
        email    = request.form["email"].strip().lower()
        password = request.form["password"]

        if not name or not email or not password:
            flash("Please fill all fields.")
            return redirect(url_for("signup"))

        if len(password) < 8:
            flash("Password must have at least 8 characters.")
            return redirect(url_for("signup"))

        try:
            with sqlite3.connect(DB) as con:
                con.execute(
                    "INSERT INTO users(name, email, password) VALUES(?, ?, ?)",
                    (name, email, generate_password_hash(password))
                )
                con.commit()

            flash("Account created! Please login.")
            return redirect(url_for("login"))

        except sqlite3.IntegrityError:
            flash("Email already registered.")
            return redirect(url_for("signup"))

    return render_template("signup.html")


# ---------------- LOGIN ----------------

@app.route("/login", methods=["GET", "POST"])
def login():

    if request.method == "POST":

        email    = request.form["email"].strip().lower()
        password = request.form["password"]

        with sqlite3.connect(DB) as con:
            con.row_factory = sqlite3.Row
            user = con.execute(
                "SELECT * FROM users WHERE email = ?",
                (email,)
            ).fetchone()

        if user and check_password_hash(user["password"], password):
            session.clear()
            session["user_id"]   = user["id"]
            session["user_name"] = user["name"]
            return redirect(url_for("dashboard"))

        flash("Invalid email or password.")

    return render_template("login.html")


# ---------------- DASHBOARD ----------------

@app.route("/dashboard")
@login_required
def dashboard():

    with sqlite3.connect(DB) as con:
        con.row_factory = sqlite3.Row
        rows = con.execute(
            "SELECT * FROM feedback WHERE user_id = ? ORDER BY id DESC",
            (session["user_id"],)
        ).fetchall()

    positive = sum(r["sentiment"] == "Positive" for r in rows)
    negative = sum(r["sentiment"] == "Negative" for r in rows)
    neutral  = sum(r["sentiment"] == "Neutral"  for r in rows)

    return render_template(
        "dashboard.html",
        name=session["user_name"],
        rows=rows,
        total=len(rows),
        positive=positive,
        negative=negative,
        neutral=neutral
    )


# ---------------- ANALYZE FEEDBACK ----------------

@app.route("/analyze", methods=["POST"])
@login_required
def analyze():

    message = request.form.get("message", "").strip()

    if not message:
        flash("Please enter feedback.")
        return redirect(url_for("dashboard"))

    if len(message) > 1000:
        flash("Feedback is too long.")
        return redirect(url_for("dashboard"))

    category, sentiment, score, keywords = analyze_feedback(message)

    with sqlite3.connect(DB) as con:
        con.execute(
            """
            INSERT INTO feedback
                (user_id, message, category, sentiment, score, keywords, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session["user_id"],
                message,
                category,
                sentiment,
                score,
                keywords,
                datetime.now().strftime("%d-%m-%Y %H:%M")
            )
        )
        con.commit()

    flash("Feedback analyzed successfully!")
    return redirect(url_for("dashboard"))


# ---------------- CSV REPORT ----------------

@app.route("/export")
@login_required
def export():

    with sqlite3.connect(DB) as con:
        rows = con.execute(
            """
            SELECT message, category, sentiment,
                   score, keywords, created_at
            FROM feedback
            WHERE user_id = ?
            """,
            (session["user_id"],)
        ).fetchall()

    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerow(["Feedback", "Category", "Sentiment",
                     "Score", "Keywords", "Date"])
    writer.writerows(rows)

    response = make_response("\ufeff" + output.getvalue())
    response.headers["Content-Disposition"] = (
        "attachment; filename=campus_feedback.csv"
    )
    response.headers["Content-Type"] = "text/csv; charset=utf-8"

    return response


# ---------------- LOGOUT ----------------

@app.route("/logout")
def logout():
    session.clear()
    flash("Logged out successfully.")
    return redirect(url_for("home"))


# ---------------- STARTUP ----------------
# Called at import time so the DB is ready on every
# Vercel cold start as well as local development.
init_db()


# ---------------- RUN APPLICATION ----------------

if __name__ == "__main__":
    app.run(debug=False, host="127.0.0.1", port=5000)
