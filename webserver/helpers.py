import os
import requests
import urllib.parse
import datetime
import math
import copy

from cs50 import SQL
from flask import redirect, render_template, request, session, url_for
from functools import wraps
from googleapiclient.discovery import build


def login_required(f):
    """
    Decorate routes to require login.

    https://flask.palletsprojects.com/en/1.1.x/patterns/viewdecorators/
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if session.get("user_id") is None:
            # Store the current url
            session["next"] = request.full_path
            return redirect("/login")
        return f(*args, **kwargs)
    return decorated_function


def check_time(time):
    parts = time.split(':')

    if len(parts) != 2 or len(parts[0]) != 2 or len(parts[1]) != 2:
        return False

    try:
        if 0 <= int(parts[0]) and int(parts[0]) < 24 and 0 <= int(parts[1]) and int(parts[1]) < 60:
            return True
        else:
            return False
    except:
        return False


# Returns True if start_time is earlier in time that end_time
def check_chronology(start_time, end_time):
    if int(start_time.split(":")[0]) > int(end_time.split(":")[0]):
        return False
    elif int(start_time.split(":")[0]) == int(end_time.split(":")[0]):
        if int(start_time.split(":")[1]) > int(end_time.split(":")[1]):
            return False
    return True


# Adds the credentials to venn.db
def credentials_to_database(credentials, user_id):
    db = SQL("sqlite:///venn.db")
    db.execute("INSERT INTO credentials (user_id, token, refresh_token, token_uri, client_id, client_secret, scopes) VALUES(?,?,?,?,?,?,?)", user_id,
               credentials.token, credentials.refresh_token, credentials.token_uri, credentials.client_id, credentials.client_secret, credentials.scopes[0])
    return credentials


# Creates a list for scopes (necessary for OAuth2.0)
def credentials_to_dict(creds):
    scopes = [creds["scopes"]]
    creds["scopes"] = scopes
    return creds


# Update the credentials in venn.db
def update_credentials(credentials, user_id):
    db = SQL("sqlite:///venn.db")
    db.execute("UPDATE credentials SET token=? WHERE user_id=?", credentials.token, user_id)
    return


# Change a list to a comma separated string
def list_to_string(unavailable):
    return ', '.join(sorted(unavailable))


def format_date_readable(date):
    return datetime.date.fromisoformat(date).strftime("%A, %B %d, %Y")


def format_date(date):
    return datetime.date.fromisoformat(date).strftime("%m/%d/%Y")


# Adds leading zeros to num
def fill(num):
    return str(num).zfill(2)


# Find the date that daylight saving time starts for a given year
def dst_start(year):
    delta = datetime.timedelta(days=1)
    date = datetime.date(int(year), 3, 1)
    sundays = 0
    while True:
        if date.weekday() == 6:
            sundays += 1
            if sundays == 2:
                return date
        date += delta


# Find the date that daylight saving time ends for a given year
def dst_end(year):
    delta = datetime.timedelta(days=1)
    date = datetime.date(int(year), 11, 1)
    sundays = 0
    while True:
        if date.weekday() == 6:
            return date
        date += delta


# Achieves O(C + I), where C is # of conflicts and I is # of possible intervals
def best_times(event, conflicts, interval):

    # Creates a start_date date object (Y, M, D)
    start_date = datetime.date.fromisoformat(event["start_date"])

    # Same as start_date
    end_date = datetime.date.fromisoformat(event["end_date"])

    # The starting time boundary for the event (earliest the event can start on a given day)
    start_time = datetime.time.fromisoformat(event["start_time"])

    # The ending time boundary for the event (latest time an event can end)
    end_time = datetime.time.fromisoformat(event["end_time"])

    start = datetime.datetime.combine(start_date, start_time, get_timezone(event["timezone"]))
    end = datetime.datetime.combine(end_date, end_time, get_timezone(event["timezone"]))

    # {DateTime, {user_id, delta_conflicts}} where when delta_conflicts = 0, we remove it from the dict
    # This is a prefix sum
    unavailable = {}

    for row in conflicts:
        conflict_start = datetime.datetime.fromisoformat(row["start_time"]).astimezone(get_timezone(event["timezone"]))
        conflict_end = datetime.datetime.fromisoformat(row["end_time"]).astimezone(get_timezone(event["timezone"]))

        # Check if we even need to consider the conflict
        # Guarantees that the conflict is in the general time range of the event
        if conflict_end < start or conflict_start > end:
            continue

        # TODO: Make the conflict time conform to the start_time and end_time of the day
        # ISSUE: Multiple day events would have to be split

        # Add the conflict to the prefix sum dictionary
        if conflict_start not in unavailable:
            unavailable[conflict_start] = {}
        if conflict_end not in unavailable:
            unavailable[conflict_end] = {}
        if row["user_id"] not in unavailable[conflict_start]:
            unavailable[conflict_start][row["user_id"]] = 0
        if row["user_id"] not in unavailable[conflict_end]:
            unavailable[conflict_end][row["user_id"]] = 0

        unavailable[conflict_start][row["user_id"]] += 1
        unavailable[conflict_end][row["user_id"]] -= 1

    # Get a sorted list of keys
    keys = sorted(unavailable)

    # UNAVAILABLE
    # {DateTime, {user_id, delta_conflicts}}

    # Gives a snapshot of how many people are unavailable starting that time until the next time
    # [{time: DateTime, people (unavailable): {user_id: cnt_conflicts}}]
    timeperiod = []
    # Adds up the positive entries of unavailable
    positive = []
    # {user_id: cnt_conflicts}
    current = {}
    current_pos = {}
    # Add an initial DateTime at 00:00 with no one
    for time in keys:
        # Update current by looking at each person's change
        for user_id in unavailable[time]:
            if user_id not in current:
                current[user_id] = 0
            if user_id not in current_pos:
                current_pos[user_id] = 0

            current[user_id] += unavailable[time][user_id]
            if unavailable[time][user_id] > 0:
                current_pos[user_id] += unavailable[time][user_id]

            if current[user_id] == 0:
                del current[user_id]
        # Update timeperiod and positive
        timeperiod.append({"time": time, "people": copy.deepcopy(current)})
        positive.append({"time": time, "people": copy.deepcopy(current_pos)})

    """
    # May delete unavailable, keys, current, and current_pos to save on memory usage
    del unavailable
    del keys
    del current
    del current_pos
    """

    date = start_date
    delta = datetime.timedelta(minutes=interval)

    # The starting time boundary for the event (earliest the event can start on a given day)
    start_time = datetime.time.fromisoformat(event["start_time"])

    # The ending time boundary for the event (latest time an event can end)
    end_time = datetime.time.fromisoformat(event["end_time"])

    # Store duration of the event
    duration = datetime.timedelta(minutes=int(event["duration"]))

    length = len(timeperiod)

    people = {}

    # For each day
    while date <= end_date:
        # start time of the interval
        dtime = datetime.datetime.combine(date, start_time, get_timezone(event["timezone"]))

        # max value for dtime
        end = datetime.datetime.combine(date, end_time, get_timezone(event["timezone"])) - duration

        # index our sums
        start_index = -1
        end_index = -1

        # For each datetime incrementation
        while dtime < end:
            people[dtime] = set()

            # Finds new start_index
            while start_index != length - 1 and timeperiod[start_index + 1]["time"] <= dtime:
                start_index += 1

            # Adds users who were initially busy
            if start_index != -1:
                for user_id in timeperiod[start_index]["people"]:
                    people[dtime].add(user_id)

            # if new start index greater than the old end index, the new end index must be greater than the new start index
            if start_index > end_index:
                end_index = start_index

            # Finds new end_index
            while end_index != length - 1 and positive[end_index + 1]["time"] <= dtime:
                end_index += 1

            # Records the number of people who become busy during the interval
            change = {}

            # Finds users who become busy during the interval
            if start_index != length - 1 and end_index != -1:

                # Find the number of conflicts users initially had
                change = copy.deepcopy(positive[start_index]["people"])

                # Save a pointer to the nunber of conflicts users have by the end of the interval
                temp = positive[end_index]["people"]

                for user_id in temp:
                    change[user_id] -= temp[user_id]
                    if change[user_id] == 0:
                        del change[user_id]

                """
                i = index + 1
                while i != length - 1 and timeperiod[i]["time"] <= dtime:
                    for user_id in unavailable[timeperiod[i]["time"]]:
                        if unavailable[timeperiod[i]["time"]][user_id] > 0:
                            people[dtime].add(user_id)
                    i += 1
                """
            # Adds users who become busy during the interval
            for user_id in change:
                people[dtime].add(user_id)

            dtime += delta

        date += datetime.timedelta(days=1)

    return people


def best_times_allday(event, conflicts):

    # Creates a start_date date object (Y, M, D)
    start_date = datetime.date.fromisoformat(event["start_date"])

    # Same as start_date
    end_date = datetime.date.fromisoformat(event["end_date"])

    date = start_date

    # Store duration of the event
    duration = datetime.timedelta(days=int(event["duration"]))

    people = {}

    # For each day
    while date <= end_date:

        people[date] = set()
        for conflict in conflicts:

            start = datetime.datetime.fromisoformat(conflict["start_time"]).astimezone(get_timezone(event["timezone"]))
            start_date = datetime.date(start.year, start.month, start.day)

            end = datetime.datetime.fromisoformat(conflict["end_time"]).astimezone(get_timezone(event["timezone"]))
            end_date = datetime.date(start.year, start.month, start.day)

            # Overlap logic from https://stackoverflow.com/questions/13513932/algorithm-to-detect-overlapping-periods
            if start_date <= date + duration and end_date >= date:
                people[date].add(conflict["user_id"])

        date += datetime.timedelta(days=1)

    return people


# Returns a timezone object given a UTC offset
def get_timezone(timezone):

    offset = int(timezone.split(":")[0])

    delta = datetime.timedelta(hours=offset)

    return datetime.timezone(delta)


def find_conflicts(start_datetime, end_datetime, conflicts, timezone):

    unavailable = set()

    for conflict in conflicts:

        start = datetime.datetime.fromisoformat(conflict["start_time"]).astimezone(timezone)

        end = datetime.datetime.fromisoformat(conflict["end_time"]).astimezone(timezone)

        # Overlap logic from https://stackoverflow.com/questions/13513932/algorithm-to-detect-overlapping-periods
        if start_datetime <= end and end_datetime >= start:
            unavailable.add(conflict["user_id"])

    return unavailable


def find_conflicts_allday(start_date, end_date, conflicts, timezone):

    unavailable = set()

    for conflict in conflicts:

        start = datetime.datetime.fromisoformat(conflict["start_time"]).astimezone(timezone)
        conflict_start = datetime.date(start.year, start.month, start.day)

        end = datetime.datetime.fromisoformat(conflict["end_time"]).astimezone(timezone)
        conflict_end = datetime.date(start.year, start.month, start.day)

        # Overlap logic from https://stackoverflow.com/questions/13513932/algorithm-to-detect-overlapping-periods
        if start_date <= conflict_end and end_date >= conflict_start:
            unavailable.add(conflict["user_id"])

    return unavailable