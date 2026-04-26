import os
import requests
from datetime import datetime, timedelta

SLACK_WEBHOOK_URL = os.environ['SLACK_WEBHOOK_URL']

API_URL = 'https://www.gdacs.org/gdacsapi/api/events/geteventlist/SEARCH'
STATE_FILE = 'last_event_id.txt'

LOOKBACK_DAYS = 30  # widened for debugging; change back to 7 once confirmed working

def get_last_event_id():
    try:
        with open(STATE_FILE, 'r') as f:
            value = int(f.read().strip())
            print(f"Read last event ID from file: {value}")
            return value
    except FileNotFoundError:
        print("State file not found — first run, defaulting to 0")
        return 0
    except Exception as e:
        print(f"Error reading state file: {e} — defaulting to 0")
        return 0

def save_last_event_id(eventid):
    with open(STATE_FILE, 'w') as f:
        f.write(str(eventid))
    print(f"Saved last event ID to file: {eventid}")

def post_to_slack(event):
    alert = event['AlertLevel'].upper()
    emoji = ':red_circle:' if alert == 'RED' else ':large_orange_circle:'
    text = (
        f"{emoji} *GDACS {alert} Alert: {event['Name']}*\n"
        f"*Country:* {event['Country']}\n"
        f"*Event ID:* {event['EventId']}\n"
        f"*Details:* {event['Description'][:200]}\n"
        f"*More info:* https://www.gdacs.org/report.aspx?eventid={event['EventId']}"
    )
    r = requests.post(SLACK_WEBHOOK_URL, json={"text": text})
    print(f"Slack response for Event ID {event['EventId']}: HTTP {r.status_code} - {r.text[:200]}")
    return r.status_code

def write_job_summary(all_events, last_id, gdacs_error=None, raw_fields=None):
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return

    with open(summary_path, "a") as f:
        f.write("## GDACS Alert Check Results\n\n")
        f.write(f"**Run time:** {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}  \n")
        f.write(f"**Lookback window:** {LOOKBACK_DAYS} days  \n")
        f.write(f"**Last known Event ID (before this run):** {last_id}  \n\n")

        if gdacs_error:
            f.write(f"⚠️ **GDACS API error:** {gdacs_error}\n")
            return

        if not all_events:
            f.write("No orange or red alerts returned by GDACS API.\n")
        else:
            f.write(f"**{len(all_events)} orange/red alert(s) found in GDACS:**\n\n")
            f.write("| Event ID | Title | Country | Level | Event Date Fields | Posted to Slack |\n")
            f.write("|----------|-------|---------|-------|-------------------|-----------------|\n")

            for event in all_events:
                event_id = int(event['EventId'])
                level = event['AlertLevel'].upper()
                emoji = "🔴" if level == "RED" else "🟠"

                date_fields = {k: v for k, v in event.items() if 'date' in k.lower() or 'time' in k.lower()}
                date_str = ", ".join(f"{k}: {v}" for k, v in date_fields.items()) or "none found"

                if event_id > last_id:
                    slack_status = f"✅ Posted (HTTP {event.get('slack_status', '?')})"
                else:
                    slack_status = "⏭️ Skipped (already seen)"

                f.write(f"| {event['EventId']} | {event['Name']} | {event['Country']} | {emoji} {level} | {date_str} | {slack_status} |\n")

        if raw_fields:
            f.write("\n### Raw fields returned by GDACS API (first event)\n\n")
            f.write("```\n")
            for k, v in raw_fields.items():
                f.write(f"{k}: {v}\n")
            f.write("```\n")

# --- Main ---

fromdate = (datetime.now() - timedelta(days=LOOKBACK_DAYS)).strftime('%Y-%m-%d')
params = {
    'alertlevel': 'orange;red',
    'fromdate': fromdate
}

print(f"Querying GDACS API with fromdate={fromdate} (lookback={LOOKBACK_DAYS} days)")

last_id = get_last_event_id()
print(f"Last known Event ID: {last_id}")

resp = requests.get(API_URL, params=params)
print(f"GDACS API response: HTTP {resp.status_code}")

if resp.status_code != 200:
    error_msg = f"HTTP {resp.status_code}: {resp.text[:200]}"
    print(f"GDACS API error: {error_msg}")
    write_job_summary([], last_id, gdacs_error=error_msg)
else:
    data = resp.json()
    all_events = data.get('Events', [])
    print(f"GDACS returned {len(all_events)} orange/red alert(s)")

    raw_fields = None
    if all_events:
        print("Sample event (first result):")
        for k, v in all_events[0].items():
            print(f"  {k}: {v}")
        raw_fields = all_events[0]

    new_count = 0
    if all_events:
        latest_id = max(int(e['EventId']) for e in all_events)
        print(f"Highest Event ID in results: {latest_id}")
        new_events = [e for e in all_events if int(e['EventId']) > last_id]
        print(f"Events with ID > {last_id}: {len(new_events)}")

        for event in new_events:
            status = post_to_slack(event)
            event['slack_status'] = status
            new_count += 1

        save_last_event_id(latest_id)

    print(f"New alerts posted to Slack: {new_count}")
    write_job_summary(all_events, last_id, raw_fields=raw_fields)
