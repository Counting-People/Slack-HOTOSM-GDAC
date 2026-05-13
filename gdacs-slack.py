import requests
import json
import os

GDACS_URL = "https://www.gdacs.org/gdacsapi/api/events/geteventlist/SEARCH"
SLACK_WEBHOOK_URL = os.environ["SLACK_WEBHOOK_URL"]
GITHUB_TOKEN = os.environ["GITHUB_TOKEN"]
GITHUB_REPO = os.environ["GITHUB_REPOSITORY"]

ALERT_RANK = {"green": 1, "orange": 2, "red": 3}


def fetch_gdacs_events():
    """Fetch all active events regardless of alert level."""
    params = {
        "alertlevel": "green;orange;red",
        "limit": 100,
    }
    response = requests.get(GDACS_URL, params=params, timeout=30)
    response.raise_for_status()
    return response.json().get("features", [])


def load_state():
    """Load stored event state dict from GitHub Actions variable."""
    url = f"https://api.github.com/repos/{GITHUB_REPO}/actions/variables/EVENT_ALERT_STATE"
    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
    }
    response = requests.get(url, headers=headers, timeout=10)
    if response.status_code == 200:
        try:
            return json.loads(response.json()["value"])
        except (json.JSONDecodeError, KeyError):
            return {}
    return {}


def save_state(state: dict):
    """Save event state dict to GitHub Actions variable (create or update)."""
    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "Content-Type": "application/json",
    }
    payload = {"name": "EVENT_ALERT_STATE", "value": json.dumps(state)}

    patch_url = f"https://api.github.com/repos/{GITHUB_REPO}/actions/variables/EVENT_ALERT_STATE"
    r = requests.patch(patch_url, headers=headers, json=payload, timeout=10)

    if r.status_code == 404:
        post_url = f"https://api.github.com/repos/{GITHUB_REPO}/actions/variables"
        requests.post(post_url, headers=headers, json=payload, timeout=10).raise_for_status()


def post_to_slack(event: dict, change_type: str):
    """Post an alert to the Slack Workflow webhook."""
    props = event["properties"]
    level = props.get("alertlevel", "").lower()
    emoji = ":red_circle:" if level == "red" else ":large_orange_circle:"

    payload = {
        "event_name": props.get("name", "Unknown event"),
        "country": props.get("country", "Unknown"),
        "description": props.get("description", "No description available."),
        "event_id": str(props.get("eventid", "")),
        "alert_level": f"{emoji} {level.capitalize()}",
        "change_type": change_type,  # "new_alert" or "escalation" — unused in Workflow Builder for now
    }

    response = requests.post(SLACK_WEBHOOK_URL, json=payload, timeout=10)
    response.raise_for_status()


def run():
    events = fetch_gdacs_events()
    stored_state = load_state()

    new_state = {}

    for event in events:
        props = event.get("properties", {})
        event_id = str(props.get("eventid", ""))
        current_level = props.get("alertlevel", "").lower()

        if not event_id or current_level not in ALERT_RANK:
            continue

        # Track all levels in state so we can detect future escalations from green
        new_state[event_id] = current_level

        # Never post alerts for green events
        if current_level == "green":
            continue

        previous_level = stored_state.get(event_id)

        if previous_level is None:
            # New orange or red event not seen before
            post_to_slack(event, "new_alert")
        elif ALERT_RANK.get(current_level, 0) > ALERT_RANK.get(previous_level, 0):
            # Alert level has increased (green→orange, green→red, orange→red)
            post_to_slack(event, "escalation")
        # Level unchanged or decreased — no alert

    save_state(new_state)
    print(f"Done. Tracked {len(new_state)} active events.")


if __name__ == "__main__":
    run()