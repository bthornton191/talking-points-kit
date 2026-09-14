"""Client for the TalkingPoints (talkingpts.org) parents API.

Covers the full lifecycle:
  1. Request an SMS verification code for a phone number.
  2. Exchange the code for an API token (persisted to a token file).
  3. Fetch the message feed and normalize it into simple message dicts.

No dependencies besides `requests`.
"""

import json
import os
import time
import datetime

import requests

API = "https://app.talkingpts.org/api/parents/v3"
AUTH = f"{API}/auth"

WEB_HEADERS = {
    "X-Mobile-Platform": "web",
    "X-Language": "en",
    "X-App-Version": "5.0.0",
}


class AuthRequired(Exception):
    """Raised when the stored token is missing, expired, or rejected."""


class APIError(Exception):
    """Raised when the API returns an unexpected response."""


def default_token_path():
    return os.environ.get(
        "TP_TOKEN_FILE", os.path.expanduser("~/.config/talkingpoints/token.json")
    )


def save_token(token_file, contact_id, token):
    os.makedirs(os.path.dirname(os.path.abspath(token_file)), exist_ok=True)
    fd = os.open(token_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(
            {"contact_id": contact_id, "token": token, "timestamp": int(time.time())},
            f,
        )


def load_token(token_file):
    try:
        with open(token_file) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


class TalkingPointsClient:
    def __init__(self, token_file=None, timeout=10):
        self.token_file = token_file or default_token_path()
        self.timeout = timeout

    def has_token(self):
        return load_token(self.token_file) is not None

    # ---- auth ------------------------------------------------------------

    def request_code(self, phone):
        """Send an SMS verification code to `phone` (digits-only string)."""
        r = requests.post(
            f"{AUTH}/request_verification_code",
            json={"number": phone, "digits": 5},
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "Origin": "https://families.talkingpts.org",
                "Referer": "https://families.talkingpts.org/",
                **WEB_HEADERS,
            },
            timeout=self.timeout,
        )
        r.raise_for_status()
        return r.json()

    def login(self, phone, code):
        """Exchange an SMS code for an API token and persist it.

        Returns {"contact_id": ..., "token": ...}.
        """
        r = requests.post(
            f"{AUTH}/login_with_code",
            json={
                "number": phone,
                "verificationCode": code,
                "hasAcceptedTOS": True,
            },
            headers={
                "Content-Type": "application/json; charset=utf-8",
                **WEB_HEADERS,
            },
            timeout=self.timeout,
        )
        if r.status_code != 200:
            raise APIError(f"login failed ({r.status_code}): {r.text}")
        contact = r.json()["data"]["contact"]
        token = contact["token"]
        contact_id = contact["_id"]
        save_token(self.token_file, contact_id, token)
        return {"contact_id": contact_id, "token": token}

    # ---- messages ---------------------------------------------------------

    def _headers(self):
        tk = load_token(self.token_file)
        if not tk:
            raise AuthRequired("no token stored; run the login flow first")
        return {
            "X-Token": tk["token"],
            "X-ContactId": tk["contact_id"],
            **WEB_HEADERS,
        }

    def fetch_raw(self, page=0, page_size=50):
        """Return the raw `data` object from the message feed endpoint."""
        r = requests.get(
            f"{API}/messages/feed?page={page}&pageSize={page_size}",
            headers=self._headers(),
            timeout=self.timeout,
        )
        if r.status_code in (401, 403):
            raise AuthRequired("token rejected; re-run the login flow")
        r.raise_for_status()
        return r.json()["data"]

    def fetch_messages(self, page=0, page_size=50, days=7):
        """Fetch and normalize recent messages.

        Returns a dict:
          {
            "status": "OK",
            "unread": <unreadCount or None>,
            "fetched_at": <unix ts>,
            "messages": [
              {"date": <iso str>, "from": <sender first name>,
               "text": <str>, "read": <bool>}, ...
            ]  # sorted newest-first, only messages newer than `days`
          }
        """
        data = self.fetch_raw(page=page, page_size=page_size)
        now = datetime.datetime.now(datetime.timezone.utc)
        cutoff = now - datetime.timedelta(days=days)

        messages = []
        for m in data["messages"]:
            created = datetime.datetime.fromisoformat(
                m["createdAt"].replace("Z", "+00:00")
            )
            if created >= cutoff:
                messages.append(
                    {
                        "date": m.get("displayDate", m["createdAt"]),
                        "from": m.get("from", {}).get("user", {}).get("firstName", "?"),
                        "text": m.get("text", "").strip(),
                        "read": m.get("read", False),
                    }
                )
        messages.sort(key=lambda x: x["date"], reverse=True)

        return {
            "status": "OK",
            "unread": data.get("unreadCount"),
            "fetched_at": int(time.time()),
            "messages": messages,
        }
