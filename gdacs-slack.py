# gdacs-slack.py
# Attempt to read GDAC Server and add disaster alerts to HOTOSM slack channel #disasdter-alerts
import os
import requests
from datetime import datetime, timedelta

SLACK_WEBHOOK_URL = os.environ['SLACK_WEBHOOK_URL']
GITHUB_TOKEN = os.environ['GITHUB_TOKEN']
GITHUB_REPO = os.environ['GITHUB_REPOSITORY']

API_URL = 'https://www.gdacs.org/gdacsapi/api/events/geteventlist/SEARCH'
GH_VARS_URL = f'https://api.github.com/repos/{GITHUB_REPO}/actions/variables/LAST_EVENT_ID'
GH_HEADERS = {
    'Authorization': f'Bearer {GITHUB_TOKEN}',
    'Accept': 'application/vnd.github+json',
    'X-GitHub-Api-Version': '2022-11-28'
}

LOOKBACK_DAYS = 30  # temporarily widened from 7 to catch more events for debugging

def get_last_event_id():
    r = requests.get(GH_VARS_URL, headers=GH_HEADERS)
    print(f"GET variable response: HTTP {r.status_code} - {r.text[:200]}")
    if r.status_code == 200:
        return int(r.json()['value'])
    return 0  # variable doesn't exist yet on first run

def save_last_event_id(eventid):
    r = requests.patch(GH_VARS_URL, headers=GH_HEADERS, json={'name': 'LAST_EVENT_ID', 'value': str(eventid)})
    print(f"PATCH variable response: HTTP {r.status_code} - {r.text[:200]}")
    if r.status_code == 404:
        r2 = requests.post(
            f'https://api.github.com/repos/{GITHUB_REPO}/actions/variables',
            headers=GH_HEADERS,
            json={'name': 'LAST_EVENT_ID', 'value': str(eventid)}
        )
        print(f"POST variable response: HTTP {r2.status_code} - {r2.text[:200]}")

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

                # Show all date-related fields to identify which one GDACS uses
                date_fields = {k: v for k, v in event.items() if 'date' in k.lower() or 'time' in k.lower()}
                date_str = ", ".join(f"{k}: {v}" for k, v in date_fields.items()) or "none found"

                if event_id > last_id:
                    slack_status = f"✅ Posted (HTTP {event.get('slack_status', '?')})"
                else:
                    slack_status = "⏭️ Skipped (already seen)"

                f.write(f"| {event['EventId']} | {event['Name']} | {event['Country']} | {emoji} {level} | {date_str} | {slack_status} |\n")

        # Show all field names and values from the first event
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
print(f"GitHub repo: {GITHUB_REPO}")

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

    # Debug: print all fields from the first event
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
