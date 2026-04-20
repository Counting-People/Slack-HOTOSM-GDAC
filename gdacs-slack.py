# gdacs-slack.py
# Attempt to read GDAC Server and add disaster alerts to HOTOSM slack channel #disasdter-alerts
import os
import requests
from datetime import datetime, timedelta

SLACK_WEBHOOK_URL = os.environ['https://hooks.slack.com/triggers/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']
GITHUB_TOKEN = os.environ['GITHUB_TOKEN']
GITHUB_REPO = os.environ['GITHUB_REPOSITORY']  # automatically set by Actions as "owner/repo"

API_URL = 'https://www.gdacs.org/gdacsapi/api/events/geteventlist/SEARCH'
GH_VARS_URL = f'https://api.github.com/repos/{GITHUB_REPO}/actions/variables/LAST_EVENT_ID'
GH_HEADERS = {
    'Authorization': f'Bearer {GITHUB_TOKEN}',
    'Accept': 'application/vnd.github+json',
    'X-GitHub-Api-Version': '2022-11-28'
}

def get_latest_eventid():
    r = requests.get(GH_VARS_URL, headers=GH_HEADERS)
    if r.status_code == 200:
        return int(r.json()['value'])
    return 0  # variable doesn't exist yet on first run

def save_latest_eventid(eventid):
    # Try to update first; if it doesn't exist, create it
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

params = {
    'alertlevel': 'orange;red',
    'fromdate': (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')
}

resp = requests.get(API_URL, params=params)
new_count = 0

if resp.status_code == 200:
    data = resp.json()
    events = data.get('Events', [])
    if events:
        latest_id = max(int(e['EventId']) for e in events)
        last_id = get_latest_eventid()
        new_events = [e for e in events if int(e['EventId']) > last_id]
        save_latest_eventid(latest_id)
        for event in new_events:
            status = post_to_slack(event)
            print(f"Posted {event['EventId']}: {status}")
            new_count += 1
    print(f"Checked {len(events)} events, posted {new_count} new")
else:
    print(f"GDACS API error: {resp.status_code}")