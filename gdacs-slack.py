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

def get_last_event_id():
    r = requests.get(GH_VARS_URL, headers=GH_HEADERS)
    if r.status_code == 200:
        return int(r.json()['value'])
    return 0  # variable doesn't exist yet on first run

def save_last_event_id(eventid):
    r = requests.patch(GH_VARS_URL, headers=GH_HEADERS, json={'name': 'LAST_EVENT_ID', 'value': str(eventid)})
    if r.status_code == 404:
        requests.post(
            f'https://api.github.com/repos/{GITHUB_REPO}/actions/variables',
            headers=GH_HEADERS,
            json={'name': 'LAST_EVENT_ID', 'value': str(eventid)}
        )

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
    if r.status_code != 200:
        print(f"Slack error {r.status_code}: {r.text}")
    return r.status_code

def write_job_summary(all_events, last_id, gdacs_error=None):
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return

    with open(summary_path, "a") as f:
        f.write("## GDACS Alert Check Results\n\n")
        f.write(f"**Run time:** {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}  \n")
        f.write(f"**Last known Event ID (before this run):** {last_id}  \n\n")

        if gdacs_error:
            f.write(f"⚠️ **GDACS API error:** {gdacs_error}\n")
            return

        if not all_events:
            f.write("No orange or red alerts returned by GDACS API.\n")
            return

        f.write(f"**{len(all_events)} orange/red alert(s) found in GDACS:**\n\n")
        f.write("| Event ID | Title | Country | Level | Posted to Slack |\n")
        f.write("|----------|-------|---------|-------|-----------------|\n")

        for event in all_events:
            event_id = int(event['EventId'])
            level = event['AlertLevel'].upper()
            emoji = "🔴" if level == "RED" else "🟠"
            if event_id > last_id:
                slack_status = f"✅ Posted (HTTP {event.get('slack_status', '?')})"
            else:
                slack_status = "⏭️ Skipped (already seen)"
            f.write(f"| {event['EventId']} | {event['Name']} | {event['Country']} | {emoji} {level} | {slack_status} |\n")

# --- Main ---

params = {
    'alertlevel': 'orange;red',
    'fromdate': (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')
}

last_id = get_last_event_id()
print(f"Last known Event ID: {last_id}")

resp = requests.get(API_URL, params=params)

if resp.status_code != 200:
    error_msg = f"HTTP {resp.status_code}: {resp.text[:200]}"
    print(f"GDACS API error: {error_msg}")
    write_job_summary([], last_id, gdacs_error=error_msg)
else:
    data = resp.json()
    all_events = data.get('Events', [])
    print(f"GDACS returned {len(all_events)} orange/red alert(s)")

    new_count = 0
    if all_events:
        latest_id = max(int(e['EventId']) for e in all_events)
        new_events = [e for e in all_events if int(e['EventId']) > last_id]

        for event in new_events:
            status = post_to_slack(event)
            event['slack_status'] = status
            print(f"Posted Event ID {event['EventId']}: HTTP {status}")
            new_count += 1

        save_last_event_id(latest_id)

    print(f"New alerts posted to Slack: {new_count}")
    write_job_summary(all_events, last_id)