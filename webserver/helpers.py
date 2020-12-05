import os
import requests
import urllib.parse
import datetime
import math
import copy

from cs50 import SQL
from flask import redirect, render_template, request, session
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

def check_chronology(start_time, end_time):
    if int(start_time.split(":")[0]) > int(end_time.split(":")[0]):
        return False
    elif int(start_time.split(":")[0]) == int(end_time.split(":")[0]):
        if int(start_time.split(":")[1]) > int(end_time.split(":")[1]):
            return False
    return True

#From https://developers.google.com/identity/protocols/oauth2/web-server
def credentials_to_database(credentials, user_id):
    db = SQL("sqlite:///venn.db")
    db.execute("INSERT INTO credentials (user_id, token, refresh_token, token_uri, client_id, client_secret, scopes) VALUES(?,?,?,?,?,?,?)", user_id, credentials.token, credentials.refresh_token, credentials.token_uri, credentials.client_id, credentials.client_secret, credentials.scopes[0])
    return credentials

def credentials_to_dict(creds):

    scopes = [creds["scopes"]]

    creds["scopes"] = scopes

    return creds

def update_credentials(credentials, user_id):
    db = SQL("sqlite:///venn.db")
    db.execute("UPDATE credentials SET token=? WHERE user_id=?", credentials.token, user_id)
    return

# interval_time is used for both start and end
def get_floor_time(keys,interval_time):
    # From https://www.geeksforgeeks.org/floor-in-a-sorted-array/
    def recursive_part(arr, low, high, x):
        if (low > high):
            return -1

        # If last element is smaller than x
        if (x >= arr[high]):
            return high

        # Find the middle point
        mid = int((low + high) / 2)

        # If middle point is floor.
        if (arr[mid] == x):
            return mid

        # If x lies between mid-1 and mid
        if (mid > 0 and arr[mid-1] <= x
                    and x < arr[mid]):
            return mid - 1

        # If x is smaller than mid,
        # floor must be in left half.
        if (x < arr[mid]):
            return recursive_part(arr, low, mid-1, x)

        # If mid-1 is not floor and x is greater than
        # arr[mid],
        return recursive_part(arr, mid + 1, high, x)
    return recursive_part(keys, 0, len(keys)-1, interval_time)

# Uses prefix sums
def best_times(event, conflicts):

    # Creates a start_date date object (Y, M, D)
    start_date = datetime.date.fromisoformat(event["start_date"])

    # Same as start_date
    end_date = datetime.date.fromisoformat(event["end_date"])

    # The starting time boundary for the event (earliest the event can start on a given day)
    start_time = datetime.time.fromisoformat(event["start_time"])

    # The ending time boundary for the event (latest time an event can end)
    end_time = datetime.time.fromisoformat(event["end_time"])

    start = datetime.datetime.combine(start_date, start_time)
    end = datetime.datetime.combine(end_date, end_time)

    # {DateTime, {user_id, delta_conflicts}}
    # where when delta_conflicts = 0, we remove it from the dict
    unavailable = {}

    for row in conflicts:
        conflict_start = datetime.datetime.fromisoformat(row["start_time"])
        conflict_end = datetime.datetime.fromisoformat(row["end_time"])

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

        unavailable[conflict_start][row["user_id"]]+=1
        unavailable[conflict_end][row["user_id"]]-=1

    # Get a sorted list of keys
    keys = sorted(unavailable)

    # UNAVAILABLE
    # {DateTime, {user_id, delta_conflicts}}

    # Gives a snapshot of how many people are unavailable starting that time until the next time
    # [{time: DateTime, people (unavailable): {user_id: cnt_conflicts}}]
    timeperiod = []
    # {user_id: cnt_conflicts}
    current = {}
    # Add an initial DateTime at 00:00 with no one
    for time in keys:
        # Update current by looking at each person's change
        for user_id in unavailable[time]:
            if user_id not in current:
                current[user_id] = 0
            current[user_id] += unavailable[time][user_id]
            if current[user_id] == 0:
                del current[user_id]
        # Update timeperiod
        timeperiod.append({"time":time,"people":copy.deepcopy(current)})

    date = start_date
    interval = int(math.ceil(int(event["duration"]) / 120) * 10)
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
        dtime = datetime.datetime.combine(date, start_time)

        # max value for dtime
        end = datetime.datetime.combine(date, end_time) - duration

        # the array that gene is making
        index = -1

        # For each datetime incrementation
        while dtime < end:
            people[dtime] = set()

            while index != length - 1 and timeperiod[index + 1]["time"] < dtime:
                index += 1

            if index != -1:
                for user_id in timeperiod[index]["people"]:
                    people[dtime].add(user_id)

            if index != length - 1:
                i = index + 1
                while i != length - 1 and timeperiod[i]["time"] < dtime:
                    for user_id in unavailable[timeperiod[i]["time"]]:
                        if unavailable[timeperiod[i]["time"]][user_id] > 0:
                            people[dtime].add(user_id)
                    i += 1

            dtime += delta

        date += datetime.timedelta(days=1)

    return people

def list_to_string(unavailable):
    return ', '.join(sorted(unavailable))

# Uses prefix sums
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

           # Overlap logic from https://stackoverflow.com/questions/13513932/algorithm-to-detect-overlapping-periods
           if datetime.date.fromisoformat(conflict["start_time"].split("T")[0]) <= date + duration and datetime.date.fromisoformat(conflict["end_time"].split("T")[0]) >= date:
               people[date].add(conflict["user_id"])

        date += datetime.timedelta(days=1)

    return people