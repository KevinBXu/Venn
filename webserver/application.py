import os
import datetime

from cs50 import SQL
from flask import Flask, flash, redirect, render_template, request, session
from flask_session import Session
from tempfile import mkdtemp
from werkzeug.exceptions import default_exceptions, HTTPException, InternalServerError
from werkzeug.security import check_password_hash, generate_password_hash
from functools import wraps

from helpers import login_required, check_time, check_chronology

# Configure application
app = Flask(__name__)

# Ensure templates are auto-reloaded
app.config["TEMPLATES_AUTO_RELOAD"] = True


# Ensure responses aren't cached
@app.after_request
def after_request(response):
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Expires"] = 0
    response.headers["Pragma"] = "no-cache"
    return response


# Configure session to use filesystem (instead of signed cookies)
app.config["SESSION_FILE_DIR"] = mkdtemp()
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_TYPE"] = "filesystem"
Session(app)

# Configure CS50 Library to use SQLite database
db = SQL("sqlite:///venn.db")

@app.route("/")
@login_required
def index():
    """Return login page"""

    return render_template("index.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    """Ask user to login"""

     # User reached route via POST (as by submitting a form via POST)
    if request.method == "POST":

        rows = db.execute("SELECT * FROM users WHERE name=? AND email=?", request.form.get("name"), request.form.get("email"))

        if len(rows) == 0:
            db.execute("INSERT INTO users (name, email) VALUES(?,?)", request.form.get("name"), request.form.get("email"))
            rows = db.execute("SELECT * FROM users WHERE name=? AND email=?", request.form.get("name"), request.form.get("email"))

        session["user_id"] = rows[0]["id"]

        return redirect("/")
    else:
        return render_template("login.html")


@app.route("/logout")
def logout():
    """Log user out"""

    # Forget any user_id
    session.clear()

    # Redirect user to login form
    return redirect("/")


@app.route("/create", methods=["GET", "POST"])
def create():
    """ Create A New Event"""
    if request.method == "POST":
        name = request.form.get("name")

        password = generate_password_hash(request.form.get("password"))

        daterange = request.form.get("daterange").split("-")
        start_date = datetime.datetime.strptime(daterange[0].strip(), "%m/%d/%Y")
        end_date = datetime.datetime.strptime(daterange[1].strip(), "%m/%d/%Y")

        start_time = request.form.get("start_time")
        end_time = request.form.get("end_time")

        if not check_time(start_time) or not check_time(end_time):
            return render_template("apology.html")

        if not check_chronology(start_time, end_time):
            return render_template("apology.html")

        # start_time += ":00"
        # end_time += ":00"

        db.execute("INSERT INTO events (name, hash, start_date, end_date, start_time, end_time, timezone) VALUES(?,?,?,?,?,?,?)", name, password, start_date, end_date, start_time, end_time, -5)

    return render_template("create.html")

@app.route("/created")
def created():
    """ Display Link To Newly Created Event """

    link = "example.com/?eid=EVENT_ID"

    return render_template("created.html", link=link)