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
import math

from helpers import login_required, check_time, check_chronology, credentials_to_database, credentials_to_dict, update_credentials, best_times, list_to_string, best_times_allday, timezone, find_conflicts, find_conflicts_allday

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

# Custom filter
app.jinja_env.filters["len"] = len
app.jinja_env.filters["list_to_string"] = list_to_string

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
API_KEY = "AIzaSyBaLDP-gD5M5hxXQSon8oIAzIYH9RNY5G0"

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
        timezone = ["-", "+"][int(request.form.get("timezone")) > 0] + request.form.get("timezone").strip("-").zfill(2) + ":00"

        daterange = request.form.get("daterange").split("-")
        start_date = daterange[0].strip().split("/")
        start_date = datetime.date(int(start_date[2]), int(start_date[0]), int(start_date[1]))
        end_date = daterange[1].strip().split("/")
        end_date = datetime.date(int(end_date[2]), int(end_date[0]), int(end_date[1]))

        if request.form.get("allday") == None:
            start_time = str(int(request.form.get("start_time_hours")) + int(request.form.get("start_time_noon"))).zfill(2) + ":" + request.form.get("start_time_minutes").zfill(2)
            end_time = str(int(request.form.get("end_time_hours")) + int(request.form.get("end_time_noon"))).zfill(2) + ":" + request.form.get("end_time_minutes").zfill(2)

            if not check_time(start_time) or not check_time(end_time):
                return render_template("apology.html")

            if not check_chronology(start_time, end_time):
                return render_template("apology.html")

            # start_time += ":00"
            # end_time += ":00"

            event_id = db.execute("INSERT INTO events (name, hash, start_date, end_date, start_time, end_time, timezone, duration) VALUES(?,?,?,?,?,?,?,?)", name, password, start_date, end_date, start_time, end_time, timezone, duration)
        else:
            event_id = db.execute("INSERT INTO events (name, hash, start_date, end_date, timezone, duration) VALUES(?,?,?,?,?,?)", name, password, start_date, end_date, timezone, duration)

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
        db.execute("DELETE FROM conflicts WHERE id= IN (SELECT conflict_id FROM event_conflicts WHERE event_id=?)", event_id)
        db.execute("DELETE FROM event_conflicts WHERE event_id=?", event_id)
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
        credentials = google.oauth2.credentials.Credentials(**creds)

        # Save credentials back to session in case access token was refreshed.
        # ACTION ITEM: In a production app, you likely want to save these
        #              credentials in a persistent database instead.
        update_credentials(credentials, session["user_id"])
        service = googleapiclient.discovery.build(API_SERVICE_NAME, API_VERSION, credentials=credentials, cache_discovery=False, developerKey=API_KEY)

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

                row = db.execute("SELECT * FROM conflicts WHERE google_id=?", event["id"])

                if len(row) == 0:

                    start = event['start'].get('dateTime')
                    if start == None:
                        start = event['start'].get('date') + "T00:00:00" + event_row[0]["timezone"]
                    end = event['end'].get('dateTime')
                    if end == None:
                        end = (datetime.date.fromisoformat(event['end'].get('date')) - datetime.timedelta(days=1)).isoformat() + "T23:59:59" + event_row[0]["timezone"]

                    # Put event into database
                    conflict_id = db.execute("INSERT INTO conflicts (user_id, start_time, end_time, google_id) VALUES(?,?,?,?)", session["user_id"], start, end, event["id"])
                else:
                    conflict_id = row[0]["id"]

                event_conflict = db.execute("SELECT * FROM event_conflicts WHERE conflict_id=? AND event_id=?", conflict_id, request.form.get("id"))

                if len(event_conflict) == 0:
                    db.execute("INSERT INTO event_conflicts (conflict_id, event_id) VALUES(?,?)", conflict_id, request.form.get("id"))

        db.execute("UPDATE members SET imported=1 WHERE user_id=? AND event_id=?", session["user_id"], event_row[0]["id"])

        return redirect(flask.url_for("view", id=request.form.get("id")))

    event = db.execute("SELECT * FROM events WHERE id=? AND id IN (SELECT event_id FROM members JOIN users ON members.user_id=users.id WHERE users.id=?)", request.args.get("id"), session["user_id"])

    if len(event) == 0:
        flash("Not a valid event")
        return redirect("/")
    event = event[0]

    # Have to pass in the join url
    # Have to pass through the best event times by GET
    rows = db.execute("SELECT * FROM members WHERE event_id=? AND user_id=? AND host=1", event["id"], session["user_id"])

    # rows will only exist if host exists
    if len(rows) != 0:
        host = True
    else:
        host = False


    if event["start"] != None:

        if event["start"].find("T") != -1:

            event_period = datetime.datetime.fromisoformat(event["start"]).strftime("%A, %B %d, %Y from %I:%M %p") + " to " + datetime.datetime.fromisoformat(event["start"]).strftime("%I:%M %p")

        else:

            event_period = datetime.date.fromisoformat(event["start"]).strftime("%A, %B %d, %Y") + " to " + datetime.date.fromisoformat(event["end"]).strftime("%A, %B %d, %Y")

        return render_template("view.html", event=event, host=host, event_period=event_period)

    # Determine the best times
    conflicts = db.execute("SELECT * FROM conflicts WHERE id IN (SELECT conflict_id FROM event_conflicts WHERE event_id=?)", request.args.get("id"))

    rows = db.execute("SELECT * FROM users WHERE id IN (SELECT members.user_id FROM members JOIN events ON events.id=members.event_id WHERE events.id=?)", event["id"])

    names = {}
    for row in rows:
        names[row["id"]] = row["name"]

    not_imported = db.execute("SELECT DISTINCT(name) FROM users JOIN members ON users.id=members.user_id WHERE members.event_id=? AND imported=0", event["id"])

    if len(not_imported) == 0:
        not_imported = False
    else:
        for i in range(len(not_imported)):
            not_imported[i] = not_imported[i]["name"]

    unavailable = {}

    if event["start_time"] == None:
        people = best_times_allday(event, conflicts)
        for time in sorted(people):
            date = datetime.date(time.year, time.month, time.day).strftime("%A, %B %d, %Y")
            if date not in unavailable:
                unavailable[date] = []
            period = {}
            period["start"] = time.strftime("%A, %B %d, %Y")
            period["end"] = (time + datetime.timedelta(days=int(event["duration"]))).strftime("%A, %B %d, %Y")
            period["people"] = []
            for user_id in people[time]:
                period["people"].append(names[user_id])
            unavailable[date].append(period)

        return render_template("view.html", event=event, host=host, unavailable=unavailable, names=names.values(), not_imported=not_imported)
    else:
        if request.args.get("interval") == None or request.args.get("interval") == "":
            interval = int(math.ceil(int(event["duration"]) / 120) * 10)
        else:
            interval = int(request.args.get("interval"))

        people = best_times(event, conflicts, interval)

        if request.args.get("max_events") == None or request.args.get("start_time_hours") == None or request.args.get("start_time_minutes") == None or request.args.get("start_time_noon") == None or request.args.get("max_events") == "" or request.args.get("start_time_hours") == "" or request.args.get("start_time_minutes") == "" or request.args.get("start_time_noon") == "":
            for time in sorted(people, key=lambda key: (len(people[key]), key)):
                date = datetime.date(time.year, time.month, time.day).strftime("%A, %B %d, %Y")
                if date not in unavailable:
                    unavailable[date] = []
                period = {}
                period["start"] = time.strftime("%I:%M %p")
                period["end"] = (time + datetime.timedelta(minutes=int(event["duration"]))).strftime("%I:%M %p")
                period["people"] = []
                for user_id in people[time]:
                    period["people"].append(names[user_id])
                unavailable[date].append(period)

            return render_template("view.html", event=event, host=host, unavailable=unavailable, names=names.values(), search=True, not_imported=not_imported)
        else:
            start_time = datetime.timedelta(hours=int(request.args.get("start_time_hours")) + int(request.args.get("start_time_noon")), minutes=int(request.args.get("start_time_minutes")))

            max_events = int(request.args.get("max_events"))

            sort = []

            for time in sorted(people, key=lambda key: (len(people[key]), abs(datetime.timedelta(hours=key.hour, minutes=key.minute) - start_time))):
                period = {}
                period["start"] = time.strftime("%I:%M %p %A, %B %d, %Y")
                period["end"] = (time + datetime.timedelta(minutes=int(event["duration"]))).strftime("%I:%M %p %A, %B %d, %Y")
                period["people"] = []
                for user_id in people[time]:
                    period["people"].append(names[user_id])
                sort.append(period)

                if len(sort) >= max_events:
                    break

            return render_template("view.html", event=event, host=host, sort=sort, names=names.values(), search=True, not_imported=not_imported)


@app.route("/export", methods=["GET", "POST"])
@login_required
def export():

    if request.method == "POST":

        host = db.execute("SELECT * FROM members WHERE event_id=? AND user_id=? AND host=1", request.form.get("id"), session["user_id"])

        if len(host) == 0:
            flash("Only the host can finalize an event")
            return redirect("/")

        # export the gcal event
        creds = db.execute("SELECT token, refresh_token, token_uri, client_id, client_secret, scopes FROM credentials WHERE user_id=?", session["user_id"])
        if len(creds) != 1:
            return flask.redirect('authorize')

        creds = credentials_to_dict(creds[0])

        # Load credentials from the session.
        credentials = google.oauth2.credentials.Credentials(**creds)

        # Save credentials back to session in case access token was refreshed.
        # ACTION ITEM: In a production app, you likely want to save these
        #              credentials in a persistent database instead.
        update_credentials(credentials, session["user_id"])
        service = googleapiclient.discovery.build(API_SERVICE_NAME, API_VERSION, credentials=credentials, cache_discovery=False, developerKey=API_KEY)

        members = db.execute("SELECT * FROM users WHERE id IN (SELECT user_id FROM members JOIN events ON members.event_id=events.id WHERE events.id=?)", request.form.get("id"))
        event = db.execute("SELECT * FROM events WHERE id=?", request.form.get("id"))[0]

        emails = []

        for member in members:
            tmp = {}
            tmp["email"] = member["email"]
            if member["id"] == session["user_id"]:
                tmp["organizer"] = True
            emails.append(tmp)

        if request.form.get("start").find("T") != -1:
            # from https://developers.google.com/calendar/v3/reference/events/insert
            calendar_event = {
                'creator': {
                    'self': True
                },
                'organizer': {
                    'self': True
                },
                'summary': event["name"],
                'start': {
                    'dateTime': request.form.get("start"),
                },
                'end': {
                    'dateTime': request.form.get("end"),
                },
                'attendees': emails,
                'reminders': {
                    'useDefault': False,
                    'overrides': [
                    {'method': 'email', 'minutes': 24 * 60},
                    {'method': 'popup', 'minutes': 10},
                    ],
                },
            }

        else:

            tz = service.settings().get(setting='timezone').execute()["value"]

            calendar_event = {
                'creator': {
                    'self': True
                },
                'organizer': {
                    'self': True
                },
                'summary': event["name"],
                'start': {
                    'date': request.form.get("start"),
                    'timezone': tz,
                },
                'end': {
                    'date': request.form.get("end"),
                    'timezone': tz,
                },
                'attendees': emails,
                'reminders': {
                    'useDefault': False,
                    'overrides': [
                    {'method': 'email', 'minutes': 24 * 60},
                    {'method': 'popup', 'minutes': 10},
                    ],
                },
            }

        service.events().insert(calendarId='primary', body=calendar_event).execute()

        db.execute("UPDATE events SET start=?, end=? WHERE id=?", request.form.get("start"), request.form.get("end"), request.form.get("id"))

        return redirect("/")

    event = db.execute("SELECT * FROM events WHERE id=?", request.args.get("id"))[0]
    conflicts = db.execute("SELECT * FROM conflicts WHERE id IN (SELECT conflict_id FROM event_conflicts WHERE event_id=?)", request.args.get("id"))
    members = db.execute("SELECT * FROM users WHERE id IN (SELECT members.user_id FROM members JOIN events ON events.id=members.event_id WHERE events.id=?)", event["id"])
    tz = timezone(event["timezone"])

    if request.args.get("event_date") != None:
        date = request.args.get("event_date").split("/")
        event_date = datetime.date(int(date[2]), int(date[0]), int(date[1]))

        start_time = datetime.time.fromisoformat(str(int(request.args.get("start_time_hours")) + int(request.args.get("start_time_noon"))).zfill(2) + ":" + request.args.get("start_time_minutes").zfill(2))
        end_time = datetime.time.fromisoformat(str(int(request.args.get("end_time_hours")) + int(request.args.get("end_time_noon"))).zfill(2) + ":" + request.args.get("end_time_minutes").zfill(2))

        start_datetime = datetime.datetime.combine(event_date, start_time, tz)
        end_datetime = datetime.datetime.combine(event_date, end_time, tz)

        unavailable = find_conflicts(start_datetime, end_datetime, conflicts, tz)

        available = set()

        for member in members:
            if member["id"] not in unavailable:
                available.add(member["name"])
            else:
                unavailable.add(member["name"])
                unavailable.remove(member["id"])

        return render_template("export.html", event_date=event_date.strftime("%A, %B %d, %Y"), start_time=start_time.strftime("%I:%M %p"), end_time=end_time.strftime("%I:%M %p"), available=list(available), unavailable=list(unavailable), name=event["name"], start=start_datetime.isoformat(), end=end_datetime.isoformat(), ID=event["id"])
    else:
        date = request.args.get("event_start_date").split("/")
        start_date = datetime.date(int(date[2]), int(date[0]), int(date[1]))

        date = request.args.get("event_end_date").split("/")
        end_date = datetime.date(int(date[2]), int(date[0]), int(date[1]))

        unavailable = find_conflicts_allday(start_date, end_date, conflicts, tz)

        available = set()

        for member in members:
            if member["id"] not in unavailable:
                available.add(member["name"])
            else:
                unavailable.add(member["name"])
                unavailable.remove(member["id"])

        return render_template("export.html", start_date=start_date.strftime("%A, %B %d, %Y"), end_date=end_date.strftime("%A, %B %d, %Y"), available=list(available), unavailable=list(unavailable), name=event["name"], start=start_date.isoformat(), end=end_date.isoformat(), ID=event["id"])

