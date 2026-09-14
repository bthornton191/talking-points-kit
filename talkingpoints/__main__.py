"""CLI for TalkingPoints programmatic access.

Subcommands:
    request-code <phone>        Send the 5-digit SMS verification code.
    login <phone> <code>        Exchange the SMS code for a token and save it.
    fetch [--days N]            Print recent messages as JSON.
    since <last_seen_file>      Print a delimited digest of messages newer
                                than the timestamp stored in the file, then
                                update the file to now.

Token is stored at $TP_TOKEN_FILE (default ~/.config/talkingpoints/token.json).
"""

import argparse
import json
import math
import sys
import time
import datetime

import requests

from .client import AuthRequired, APIError, TalkingPointsClient

RequestException = requests.RequestException


def _message_ts(date):
    """Parse a message timestamp to an aware datetime (assume UTC if naive)."""
    ts = datetime.datetime.fromisoformat(date.replace("Z", "+00:00"))
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=datetime.timezone.utc)
    return ts


def _digest(messages, cutoff):
    """Render messages newer than `cutoff` into a delimited text block."""
    parts = []
    for m in messages:
        date = m.get("date", "")
        if date:
            try:
                if _message_ts(date).timestamp() < cutoff:
                    continue
            except ValueError:
                pass
        parts.append(
            "--------------\n"
            f"From: {m['from']}\n"
            "--------------\n"
            f"<start_message>\n{m['text']}\n<end_message>\n"
        )
    return "".join(parts) if parts else "No new talking points messages"


def _read_last_seen(path):
    try:
        with open(path) as f:
            return float(f.read().strip())
    except (FileNotFoundError, ValueError):
        return None


def _write_last_seen(path, ts):
    with open(path, "w") as f:
        f.write(str(ts))


def main(argv=None):
    p = argparse.ArgumentParser(prog="talkingpoints")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("request-code", help="send an SMS verification code")
    s.add_argument("phone")

    s = sub.add_parser("login", help="exchange SMS code for a token")
    s.add_argument("phone")
    s.add_argument("code")

    s = sub.add_parser("fetch", help="print recent messages as JSON")
    s.add_argument("--days", type=int, default=7)
    s.add_argument("--page-size", type=int, default=50)

    s = sub.add_parser("since", help="print digest of messages since last run")
    s.add_argument("last_seen_file", help="file storing a unix timestamp")
    s.add_argument("--fallback-hours", type=int, default=48)

    args = p.parse_args(argv)
    c = TalkingPointsClient()

    try:
        if args.cmd == "request-code":
            print(json.dumps(c.request_code(args.phone)))
        elif args.cmd == "login":
            print(json.dumps(c.login(args.phone, args.code)))
        elif args.cmd == "fetch":
            print(json.dumps(c.fetch_messages(days=args.days, page_size=args.page_size)))
        elif args.cmd == "since":
            cutoff = _read_last_seen(args.last_seen_file)
            if cutoff is None:
                cutoff = (
                    datetime.datetime.now(datetime.timezone.utc)
                    - datetime.timedelta(hours=args.fallback_hours)
                ).timestamp()
            # window must cover everything back to the cutoff, not just 7 days
            days = max(7, math.ceil((time.time() - cutoff) / 86400) + 1)
            result = c.fetch_messages(days=days)
            print(_digest(result["messages"], cutoff))
            _write_last_seen(args.last_seen_file, time.time())
    except AuthRequired as e:
        print(json.dumps({"status": "LOGIN_REQUIRED", "error": str(e)}))
        sys.exit(2)
    except APIError as e:
        print(json.dumps({"status": "ERROR", "error": str(e)}))
        sys.exit(1)
    except RequestException as e:
        print(json.dumps({"status": "ERROR", "error": str(e)}))
        sys.exit(1)


if __name__ == "__main__":
    main()
