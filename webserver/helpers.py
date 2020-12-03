import os
import requests
import urllib.parse

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


def get_calendar():

    service = build('calendar', 'v3')

    return

#From https://developers.google.com/identity/protocols/oauth2/web-server
def credentials_to_dict(credentials):
  return {'token': credentials.token,
          'refresh_token': credentials.refresh_token,
          'token_uri': credentials.token_uri,
          'client_id': credentials.client_id,
          'client_secret': credentials.client_secret,
          'scopes': credentials.scopes}