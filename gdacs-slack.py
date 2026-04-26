## read the GDACS Alert URL and post new Orange or Red alerts to the HOT Slack channel #disaster-alerts
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

def post_to_slack(props):
    alert = props['alertlevel'].upper()
    emoji = ':red_circle:' if alert == 'RED' else ':large_orange_circle:'
    text = (
        f"{emoji} *GDACS {alert} Alert: {props['name']}*\n"
        f"*Country:* {props['country']}\n"
        f"*Event ID:* {props['eventid']}\n"
        f"*From:* {props.get('fromdate', 'unknown')[:10]}  *To:* {props.get('todate', 'unknown')[:10]}\n"
        f"*Last updated:* {props.get('datemodified', 'unknown')[:10]}\n"
        f"*Details:* {props['description'][:200]}\n"
        f"*More info:* https://www.gdacs.org/report.aspx?eventid={props['eventid']}&episodeid={props.get('episodeid', '')}&eventtype={props.get('eventtype', '')}"
    )
    r = requests.post(SLACK_WEBHOOK_URL, json={"text": text})
    print(f"Slack response for Event ID {props['eventid']}: HTTP {r.status_code} - {r.text[:200]}")
    return r.status_code

def write_job_summary(all_features, last_id, gdacs_error=None, raw_fields=None):
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

        if not all_features:
            f.write("No orange or red alerts returned by GDACS API.\n")
        else:
            f.write(f"**{len(all_features)} orange/red alert(s) found in GDACS:**\n\n")
            f.write("| Event ID | Title | Country | Level | From | To | Last Updated | Posted to Slack |\n")
            f.write("|----------|-------|---------|-------|------|----|--------------|----------------|\n")

            for feature in all_features:
                props = feature['properties']
                event_id = int(props['eventid'])
                level = props['alertlevel'].upper()
                emoji = "🔴" if level == "RED" else "🟠"
                fromdate = props.get('fromdate', '')[:10]
                todate = props.get('todate', '')[:10]
                datemodified = props.get('datemodified', '')[:10]

                if event_id > last_id:
                    slack_status = f"✅ Posted (HTTP {props.get('slack_status', '?')})"
                else:
                    slack_status = "⏭️ Skipped (already seen)"

                f.write(f"| {props['eventid']} | {props['name']} | {props['country']} | {emoji} {level} | {fromdate} | {todate} | {datemodified} | {slack_status} |\n")

        if raw_fields:
            f.write("\n### Raw fields returned by GDACS API (first event properties)\n\n")
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
print(f"Full request URL: {resp.url}")

if resp.status_code != 200:
    error_msg = f"HTTP {resp.status_code}: {resp.text[:200]}"
    print(f"GDACS API error: {error_msg}")
    write_job_summary([], last_id, gdacs_error=error_msg)
else:
    data = resp.json()
    all_features = data.get('features', [])
    print(f"GDACS returned {len(all_features)} orange/red alert(s)")

    raw_fields = None
    if all_features:
        print("Sample event properties (first result):")
        for k, v in all_features[0]['properties'].items():
            print(f"  {k}: {v}")
        raw_fields = all_features[0]['properties']

    new_count = 0
    if all_features:
        latest_id = max(int(f['properties']['eventid']) for f in all_features)
        print(f"Highest Event ID in results: {latest_id}")
        new_features = [f for f in all_features if int(f['properties']['eventid']) > last_id]
        print(f"Events with ID > {last_id}: {len(new_features)}")

        for feature in new_features:
            props = feature['properties']
            status = post_to_slack(props)
            props['slack_status'] = status
            new_count += 1

        save_last_event_id(latest_id)

    print(f"New alerts posted to Slack: {new_count}")
    write_job_summary(all_features, last_id, raw_fields=raw_fields)
