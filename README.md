# talking-points-kit

A generic toolkit for programmatically accessing messages from
[TalkingPoints](https://talkingpts.org/) (the `app.talkingpts.org` parent
communication app schools use to message families). Everything here is
platform-agnostic plain Python — use it from a cron job, a server, an
automation tool, or an LLM pipeline.

## What you get

```
talkingpoints/
  __init__.py        library exports
  client.py          TalkingPointsClient (auth + message feed)
  __main__.py        CLI: python3 -m talkingpoints <subcommand>
examples/
  consume_messages.py  minimal "what's new since last time" consumer
requirements.txt    requests
```

## Authentication

TalkingPoints' parent API uses phone-number login with a 5-digit SMS code.
The flow is:

1. **Request a code** — `POST /api/parents/v3/auth/request_verification_code`
   ```json
   {"number": "<digits-only phone>", "digits": 5}
   ```
   The API texts a 5-digit code to that number.

2. **Exchange the code for a token** —
   `POST /api/parents/v3/auth/login_with_code`
   ```json
   {"number": "<digits-only phone>", "verificationCode": "<5 digits>", "hasAcceptedTOS": true}
   ```
   Response: `data.contact.token` (API token) and `data.contact._id`
   (contact id). Both must be persisted; they are the credentials for all
   subsequent calls.

3. **Call the API with session headers**
   ```
   X-Token: <token>
   X-ContactId: <contact id>
   X-Mobile-Platform: web
   X-Language: en
   X-App-Version: 5.0.0
   ```

When the API answers `401` or `403`, the token is missing/expired — re-run
steps 1–2. The client raises `AuthRequired` (CLI exits with status `2` and
prints `{"status": "LOGIN_REQUIRED"}`) so you can hook your own re-auth
flow: prompt for the code, or automate "code request → SMS arrives →
submit code" in whatever notification system you have.

## Fetching messages

`GET /api/parents/v3/messages/feed?page=0&pageSize=50`

Response shape:

```
data.messages[]        newest feed items (paged)
data.unreadCount       int
```

Each message contains the fields this kit normalizes:

| field       | meaning                                    |
|-------------|--------------------------------------------|
| `createdAt` | ISO 8601 UTC timestamp (`...Z`)            |
| `displayDate` | display timestamp (fallback for `date`)  |
| `from.user.firstName` | sender's first name              |
| `text`      | message body                               |
| `read`      | read flag                                  |

### Library usage

```python
from talkingpoints import TalkingPointsClient, AuthRequired

c = TalkingPointsClient()          # token file: $TP_TOKEN_FILE
try:
    feed = c.fetch_messages(days=7)   # messages from the last 7 days
except AuthRequired:
    c.request_code("<phone>")
    code = input("SMS code: ")
    c.login("<phone>", code)
    feed = c.fetch_messages(days=7)

for m in feed["messages"]:
    print(m["date"], m["from"], m["text"])
```

The token file is written on successful `login()` (dir created as needed).

### CLI usage

```bash
pip install requests

# one-time (or whenever the token expires):
python3 -m talkingpoints request-code 5551234567
python3 -m talkingpoints login 5551234567 12345      # code from the SMS

# then, on any schedule:
python3 -m talkingpoints fetch --days 7            # JSON feed
python3 -m talkingpoints since state/last_seen     # human/LLM digest
```

`since` prints messages that arrived after the unix timestamp stored in
`last_seen_file` (defaulting to the last 48h if the file is empty/missing),
renders them as a delimited block, then writes "now" into the file:

```
--------------
From: Elise
--------------
<start_message>
Good evening Kenwood families, ...
<end_message>
```

This block format is the recommended interchange format when feeding
messages to an LLM or another consumer — it preserves sender boundaries and
is trivial to split on `<start_message>`/`<end_message>`.

## "New messages since last run" pattern

There is no server-side "mark read" cursor used here, so dedupe must be
client-side. The pattern (implemented in `talkingpoints/__main__.py` and
`examples/consume_messages.py`):

1. Persist a single unix timestamp ("last seen") somewhere durable.
2. On each run, load it; if absent, fall back to `now - 48h`.
3. Filter `messages` where `date` parses to a timestamp `>=` the cutoff.
4. Render/handle the survivors, then overwrite the file with the current
   time.

For LLM consumption, prefer rendering the text block (as above) rather than
raw JSON — it keeps prompts small and unambiguous.

## Operational notes

- Polling every few hours is plenty; the feed endpoint is a standard web
  API used by the web client. `fetch_messages()` paginates automatically
  until the requested window is covered, so long downtimes don't cause
  gaps.
- Keep the token file private — it grants full read access to your
  account's messages. The client creates it with `0600` permissions
  automatically.
- The phone number must be digits-only (no `+`, spaces, or dashes).
- If messages seem stuck in the past, your token likely expired: the client
  will signal `LOGIN_REQUIRED`; rerun the request-code → login flow.

## Origin

This kit is extracted from a Home Assistant setup where the same three
scripts (request code / login / fetch) ran as shell commands and the fetch
output fed a command-line sensor used by a morning-briefing automation.
Nothing here depends on Home Assistant.
