import os
import datetime

from cs50 import SQL
import flask
from flask import Flask, flash, redirect, render_template, request, session
from flask_session import Session
import requests
from tempfile import mkdtemp
from werkzeug.exceptions import default_exceptions, HTTPException, InternalServerError
from werkzeug.security import check_password_hash, generate_password_hash
from functools import wraps
import google.oauth2.credentials
import google_auth_oauthlib.flow
import googleapiclient.discovery

from helpers import login_required, check_time, check_chronology, credentials_to_database, credentials_to_dict, update_credentials

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

# Google Oauth routes (authorize, oatuh2callback) from https://developers.google.com/identity/protocols/oauth2/web-server
# This variable specifies the name of a file that contains the OAuth 2.0
# information for this application, including its client_id and client_secret.
CLIENT_SECRETS_FILE = "../../../client_secret_544895891085-c0ee6mvu0fgpl9ki745i06crhlc67o2o.apps.googleusercontent.com.json"

# This OAuth 2.0 access scope allows for full read/write access to the
# authenticated user's account and requires requests to use an SSL connection.
SCOPES = ['https://www.googleapis.com/auth/calendar']
API_SERVICE_NAME = 'calendar'
API_VERSION = 'v3'

@app.route("/")
@login_required
def index():

    name = db.execute("SELECT name FROM users WHERE id=?", session["user_id"])[0]["name"]

    events = db.execute("SELECT name, events.id, start_date, end_date FROM events JOIN members ON events.id=members.event_id WHERE members.user_id=?", session["user_id"])

    for event in events:
        event["view"] = flask.url_for('view', _external=True, id=str(event["id"]))
        event["link"] = flask.url_for('join', _external=True, id=str(event["id"]))

    return render_template("index.html", events=events, name=name)


@app.route('/authorize')
def authorize():
    # Create flow instance to manage the OAuth 2.0 Authorization Grant Flow steps.
    flow = google_auth_oauthlib.flow.Flow.from_client_secrets_file(
        CLIENT_SECRETS_FILE, scopes=SCOPES)

    # The URI created here must exactly match one of the authorized redirect URIs
    # for the OAuth 2.0 client, which you configured in the API Console. If this
    # value doesn't match an authorized URI, you will get a 'redirect_uri_mismatch'
    # error.
    tmp_url = flask.url_for('oauth2callback', _external=True)
    if "http:" in tmp_url:
        tmp_url = "https:" + tmp_url[5:]
    flow.redirect_uri = tmp_url

    tmp_url, state = flow.authorization_url(
        # Enable offline access so that you can refresh an access token without
        # re-prompting the user for permission. Recommended for web server apps.
        access_type='offline'
    )

    # http to https from https://github.com/requests/requests-oauthlib/issues/287
    if "http:" in tmp_url:
        tmp_url = "https:" + tmp_url[5:]
    authorization_url = tmp_url

    # Store the state so the callback can verify the auth server response.
    flask.session['state'] = state

    return flask.redirect(authorization_url)


@app.route('/oauth2callback')
def oauth2callback():
    # Specify the state when creating the flow in the callback so that it can
    # verified in the authorization server response.
    state = flask.session['state']

    flow = google_auth_oauthlib.flow.Flow.from_client_secrets_file(
      CLIENT_SECRETS_FILE, scopes=SCOPES, state=state)
    tmp_url = flask.url_for('oauth2callback', _external=True)
    if "http:" in tmp_url:
        tmp_url = "https:" + tmp_url[5:]
    flow.redirect_uri = tmp_url

    # Use the authorization server's response to fetch the OAuth 2.0 tokens.
    tmp_url = flask.request.url
    if "http:" in tmp_url:
        tmp_url = "https:" + tmp_url[5:]
    authorization_response = tmp_url
    flow.fetch_token(authorization_response=authorization_response)

    # Store credentials in the session.
    # ACTION ITEM: In a production app, you likely want to save these
    #              credentials in a persistent database instead.
    credentials = flow.credentials
    credentials_to_database(credentials, session["user_id"])

    return flask.redirect("/")


@app.route("/create", methods=["GET", "POST"])
@login_required
def create():
    """ Create A New Event"""
    if request.method == "POST":
        name = request.form.get("name")

        password = generate_password_hash(request.form.get("password"))

        duration = int(request.form.get("duration"))

        #["", "+"][total > 0] from https://stackoverflow.com/questions/2763432/how-to-print-the-sign-of-a-digit-for-positive-numbers-in-python
        timezone = ["", "+"][int(request.form.get("timezone")) > 0] + request.form.get("timezone").zfill(2) + ":00"

        daterange = request.form.get("daterange").split("-")
        start_date = daterange[0].strip().split("/")
        start_date = datetime.date(int(start_date[2]), int(start_date[0]), int(start_date[1]))
        end_date = daterange[1].strip().split("/")
        end_date = datetime.date(int(end_date[2]), int(end_date[0]), int(end_date[1]))

        start_time = str(int(request.form.get("start_time_hours")) + int(request.form.get("start_time_noon"))).zill(2) + ":" + request.form.get("start_time_minutes")
        end_time = str(int(request.form.get("end_time_hours")) + int(request.form.get("end_time_noon"))).zfill(2) + ":" + request.form.get("end_time_minutes")

        if not check_time(start_time) or not check_time(end_time):
            return render_template("apology.html")

        if not check_chronology(start_time, end_time):
            return render_template("apology.html")

        # start_time += ":00"
        # end_time += ":00"

        event_id = db.execute("INSERT INTO events (name, hash, start_date, end_date, start_time, end_time, timezone, duration) VALUES(?,?,?,?,?,?,?,?)", name, password, start_date, end_date, start_time, end_time, timezone, duration)
        db.execute("INSERT INTO members (event_id, user_id, host) VALUES(?,?,?)", event_id, session["user_id"], True)

        url = flask.url_for("join", _external=True) + "?id=" + str(event_id)

        return render_template("created.html", URL=url, PASSWORD=request.form.get("password"))

    return render_template("create.html")


@app.route("/delete", methods=["GET","POST"])
@login_required
def delete():
    """ Delete an Event"""
    if request.method == "POST":
        event_id = request.form.get("id")

        event = db.execute("SELECT * FROM events WHERE id=?", event_id)

        # If attempting to delete an event that doesn't exist
        if len(event) != 1:
            flash("Invalid event!")
            return redirect(flask.url_for("view", id=event_id))

        # Only the host should be able to delete the event
        rows = db.execute("SELECT * FROM members WHERE event_id=? AND user_id=? AND host=1", event_id, session["user_id"])

        if len(rows) == 0:
            flash("Only the host can delete this event!")
            return redirect(flask.url_for("view", id=event_id))

        # events, conflicts, members
        db.execute("DELETE FROM events WHERE id=?", event_id)
        db.execute("DELETE FROM conflicts WHERE event_id=?", event_id)
        db.execute("DELETE FROM members WHERE event_id=?", event_id)

        return redirect("/")

    event_id = request.args.get("id")

    event = db.execute("SELECT * FROM events WHERE id=?", event_id)

    # If attempting to delete an event that doesn't exist
    if len(event) != 1:
        flash("Invalid event!")
        return redirect(flask.url_for("view", id=event_id))

    # Only the host should be able to delete the event
    rows = db.execute("SELECT * FROM members WHERE event_id=? AND user_id=? AND host=1", event_id, session["user_id"])

    if len(rows) == 0:
        flash("Only the host can delete this event!")
        return redirect(flask.url_for("view", id=event_id))

    return render_template("delete.html", name=event[0]["name"], ID=event_id)


@app.route("/join", methods=["GET", "POST"])
@login_required
def join():
    """Join an Event"""
    if request.method == "POST":

        rows = db.execute("SELECT * FROM events WHERE id=?", request.form.get("id"))

        if len(rows) != 1 or not check_password_hash(rows[0]["hash"], request.form.get("password")):
            flash("Incorrect ID or Password. Please Try Again.")
            return render_template("join.html", ID=request.form.get("id"))

        rows = db.execute("SELECT * FROM members WHERE event_id=? AND user_id=?", int(request.form.get("id")), session["user_id"])
        # If user already joined, then just redirect to /view
        if len(rows) != 0:
            return redirect("/")

        db.execute("INSERT INTO members (event_id, user_id) VALUES(?,?)", int(request.form.get("id")), session["user_id"])

        return redirect(flask.url_for("view", id=request.form.get("id")))

    # Redirect user to login form
    return render_template("join.html", ID=request.args.get("id"))


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


@app.route("/view", methods=["GET", "POST"])
@login_required
def view():

    if request.method == "POST": #AKA If they submit the form to add their GCal...

        creds = db.execute("SELECT token, refresh_token, token_uri, client_id, client_secret, scopes FROM credentials WHERE user_id=?", session["user_id"])
        if len(creds) != 1:
            return flask.redirect('authorize')

        creds = credentials_to_dict(creds[0])

        # Load credentials from the session.
        credentials = google.oauth2.credentials.Credentials(
          **creds)

        # Save credentials back to session in case access token was refreshed.
        # ACTION ITEM: In a production app, you likely want to save these
        #              credentials in a persistent database instead.
        update_credentials(credentials, session["user_id"])

        service = googleapiclient.discovery.build(
            API_SERVICE_NAME, API_VERSION, credentials=credentials, cache_discovery=False)

        # Gather all calendar IDs
        calendars = []

        page_token = None
        while True:
            calendar_list = service.calendarList().list(pageToken=page_token).execute()
            for calendar_list_entry in calendar_list['items']:
                calendars.append(calendar_list_entry['id'])
            page_token = calendar_list.get('nextPageToken')
            if not page_token:
                break

        event_row = db.execute("SELECT * FROM events WHERE id=?", request.form.get("id"))

        if len(event_row) == 0:
            flash("Not a valid event")
            return redirect("/")

        start_date = event_row[0]["start_date"] + "T00:00:00" + event_row[0]["timezone"]
        end_date = event_row[0]["end_date"] + "T23:59:59" + event_row[0]["timezone"]

        for calendar in calendars:
            events_result = service.events().list(calendarId=calendar, timeMax=end_date, timeMin=start_date, singleEvents=True, orderBy='startTime', timeZone=event_row[0]["timezone"]).execute()
            events = events_result.get('items', [])

            # "start": { # The (inclusive) start time of the event. For a recurring event, this is the start time of the first instance.
            # "dateTime": "A String", # The time, as a combined date-time value (formatted according to RFC3339). A time zone offset is required unless a time zone is explicitly specified in timeZone.
            # "date": "A String", # The date, in the format "yyyy-mm-dd", if this is an all-day event.
            # "timeZone": "A String", # The time zone in which the time is specified. (Formatted as an IANA Time Zone Database name, e.g. "Europe/Zurich".) For recurring events this field is required and specifies the time zone in which the recurrence is expanded. For single events this field is optional and indicates a custom time zone for the event start/end.
            # },
            for event in events:

                row = db.execute("SELECT * FROM conflicts WHERE id=?", event["id"])

                if len(row) == 0:

                    start = event['start'].get('dateTime')
                    if start == None:
                        start = event['start'].get('date') + "T00:00:00"
                    else:
                        start = start[:19]
                    end = event['end'].get('dateTime')
                    if end == None:
                        end = event['end'].get('date') + "T00:00:00"
                    else:
                        end = end[:19]

                    # Put event into database
                    db.execute("INSERT INTO conflicts (event_id, user_id, start_time, end_time, id) VALUES(?,?,?,?,?)", event_row[0]['id'], session["user_id"], start, end, event["id"])

        return redirect(flask.url_for("view", id=request.form.get("id")))

    event = db.execute("SELECT * FROM events WHERE id=? AND id IN (SELECT event_id FROM members JOIN users ON members.user_id=users.id WHERE users.id=?)", request.args.get("id"), session["user_id"])

    if len(event) == 0:
        flash("Not a valid event")
        return redirect("/")
    # Have to pass in the join url
    # Have to pass through the best event times by GET
    rows = db.execute("SELECT * FROM members WHERE event_id=? AND user_id=? AND host=1", event[0]["id"], session["user_id"])

    # rows will only exist if host exists
    if len(rows) != 0:
        host = True
    else:
        host = False

    # Determine the best times
    conflicts = db.execute("SELECT * FROM conflicts WHERE event_id=?", request.args.get("id"))

    # Stores number of conflicts for each time interval we have
    num_conflicts = {}

    # Creates a start_date date object (Y, M, D)
    start = event[0]["start_date"].split("-")
    start_date = datetime.date(int(start[0]), int(start[1]), int(start[2]))

    # Same as start_date
    end = event[0]["end_date"].split("-")
    end_date = datetime.date(int(end[0]), int(end[1]), int(end[2]))

    # For while loop to increment the date
    date = start_date

    # 10 minute intervals
    interval = 10
    delta = datetime.timedelta(minutes=interval)

    # The starting time boundary for the event (earliest the event can start on a given day)
    start_time = event[0]["start_time"].split(":")
    start_time = datetime.time(int(start_time[0]), int(start_time[1]))

    # The ending time boundary for the event (latest time an event can end)
    end_time = event[0]["end_time"].split(":")
    end_time = datetime.time(int(end_time[0]), int(end_time[1]))

    # Store duration of the event
    duration = datetime.timedelta(minutes=int(event[0]["duration"]))

    while date <= end_date:
        # start time of the interval
        dtime = datetime.datetime(date.year, date.month, date.day, start_time.hour, start_time.minute)

        # max value for dtime
        end = datetime.datetime(date.year, date.month, date.day, end_time.hour, end_time.minute) - duration

        # For each datetime incrementation
        while dtime < end:
            num_conflicts[dtime] = 0
            for conflict in conflicts:
                # logic from https://stackoverflow.com/questions/13513932/algorithm-to-detect-overlapping-periods
                if datetime.datetime.fromisoformat(conflict["start_time"]) < dtime + duration and datetime.datetime.fromisoformat(conflict["end_time"]) > dtime:
                    num_conflicts[dtime] += 1
            dtime += delta

        date += datetime.timedelta(days=1)

    print(num_conflicts)
    return render_template("view.html", event=event[0], host=host)


@app.route("/test")
def test():
    creds = db.execute("SELECT user_id, token, refresh_token, token_uri, client_id, client_secret, scopes FROM credentials WHERE user_id=?", session["user_id"])
    creds = credentials_to_dict(creds[0])
    for test in creds:
        print(test)
        print(creds[test])
        print(type(creds[test]))
    return redirect ("/")


# Uses prefix sums
def best_times(event_id):

    # TreeMap<DateTime, Pair<HashSet<user_id>,int (-1 or 1)>>
    # HashMap<DateTime, HashSet<user_id>>

    # start_date, end_date, start_time, end_time, duration
    event = db.execute("SELECT * FROM events WHERE id=?", event_id)
    event = event[0]

    duration = int(event["duration"])

    # Determine the boundaries for best times (since entries that are 0 will not appear)
    start = event["start_date"].split("-")
    start_date = datetime.date(int(start[0]), int(start[1]), int(start[2]))

    end = event["end_date"].split("-")
    end_date = datetime.date(int(end[0]), int(end[1]), int(end[2]))

    start_time = event["start_time"].split(":")
    start_time = datetime.time(int(start_time[0]), int(start_time[1]))
    end_time = event["end_time"].split(":")
    end_time = datetime.time(int(end_time[0]), int(end_time[1]))

    start = datetime.combine(start_date, start_time)
    end = datetime.combine(end_date, end_time)

    """
    # How to make a custom DateTime variable
    start = datetime.datetime(start_date.year, start_date.month, start_date.day, start_time.hour, start_time.minute)
    # start = datetime.combine(start_date, start_time)
    end = datetime.datetime(end_date.year, end_date.month, end_date.day, end_time.hour, end_time.minute)

    # How to add time
    delta = datetime.timedelta(minutes=10)

    # How to convert string from database to DateTime
    datetime.datetime.fromisoformat(conflict["start_time"])
    """

    # Start with:
    # Dict<DateTime, int>
    # Since we might just be able to check who's available when afterwards with little cost

    # user_id, start_time, end_time
    conflicts = db.execute("SELECT * FROM conflicts WHERE event_id=?", event_id)

    unavailable = {}

    """
    for conflict in conflicts:
        conflict_start = datetime.datetime.fromisoformat(conflict["start_time"])
        conflict_end = datetime.datetime.fromisoformat(conflict["end_time"])

        # Check if we even need to consider the conflict
        # Guarantees that the conflict is in the general time range of the event
        if conflict_end < start or conflict_start > end:
            continue
        # For example, checks if the conflict starts after 9:00 PM and ends before 9:00 AM (where the possible time window is 9:00 AM~9:00 PM)
        elif (conflict_start.hour > end.hour or conflict_start.minute > end.minute) and (conflict_end.hour < start.hour or conflict_end.minute < start.minute):
            continue
        
        # Make the conflict time conform to the start_time and end_time of the day
        if conflict_start.hour > end.hour or conflict_start.minute > end.minute:
            

    """

    # Desired end result:
    # Dict<(start_time, end_time), people_available>
    # people_available can eventually represent a list of people available

