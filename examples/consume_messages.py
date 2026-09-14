"""Minimal consumer: print new TalkingPoints messages since the last run.

Usage:
    python3 consume_messages.py <phone> <last_seen_file>

First run: falls back to the last 48 hours. Later runs only show what
arrived since the previous run.
"""

import datetime
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from talkingpoints import AuthRequired, TalkingPointsClient


def read_last_seen(path):
    try:
        with open(path) as f:
            return float(f.read().strip())
    except (FileNotFoundError, ValueError):
        return None


def write_last_seen(path, ts):
    with open(path, "w") as f:
        f.write(str(ts))


def main():
    if len(sys.argv) != 3:
        sys.exit(f"Usage: {sys.argv[0]} <phone> <last_seen_file>")
    phone, last_seen_file = sys.argv[1], sys.argv[2]
    c = TalkingPointsClient()

    try:
        feed = c.fetch_messages()
    except AuthRequired:
        c.request_code(phone)
        code = input(f"Enter the SMS code sent to {phone}: ")
        c.login(phone, code)
        feed = c.fetch_messages()

    cutoff = read_last_seen(last_seen_file)
    if cutoff is None:
        cutoff = (
            datetime.datetime.now(datetime.timezone.utc)
            - datetime.timedelta(hours=48)
        ).timestamp()

    new = [
        m
        for m in feed["messages"]
        if datetime.datetime.fromisoformat(m["date"].replace("Z", "+00:00")).timestamp()
        >= cutoff
    ]

    if not new:
        print("No new talking points messages")
    for m in new:
        print(f"--------------\nFrom: {m['from']}\n--------------")
        print(m["text"])
        print()

    write_last_seen(last_seen_file, datetime.datetime.now().timestamp())


if __name__ == "__main__":
    main()
