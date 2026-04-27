import requests
import json
import os
import xml.etree.ElementTree as ET

# Configuration
GDACS_URL = "https://www.gdacs.org/xml/rss.xml"
SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL")
STATE_FILE = "last_event_id.txt"

def get_last_event_id():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r") as f:
            return f.read().strip()
    return "0"

def save_last_event_id(event_id):
    with open(STATE_FILE, "w") as f:
        f.write(str(event_id))

def get_gdacs_alerts(last_id):
    try:
        response = requests.get(GDACS_URL, timeout=15)
        response.raise_for_status()
        root = ET.fromstring(response.content)
        
        alerts = []
        # Find all items in the RSS channel
        for item in root.findall(".//item"):
            # WILDCARD SEARCH: Finds tags regardless of namespace prefix
            def get_tag_text(tag_name, default=""):
                # Searches for a tag ending with the specific name (ignores namespace)
                el = item.find(f".//{{*}}{tag_name}")
                if el is None:
                    # Fallback for standard tags like <title> or <link>
                    el = item.find(tag_name)
                return el.text.strip() if el is not None and el.text else default

            event_id = get_tag_text("eventid")
            alert_level = get_tag_text("alertlevel", "Green")
            country = get_tag_text("country", "Unknown")
            title = get_tag_text("title", "No Title Found")
            link = get_tag_text("link", "https://www.gdacs.org")
            description = get_tag_text("description", "")

            # If we hit our checkpoint, stop processing older items
            if event_id == last_id and last_id != "0":
                break
                
            if alert_level.upper() in ["ORANGE", "RED"]:
                alerts.append({
                    "title": title,
                    "country": country,
                    "event_id": event_id,
                    "alert_level": alert_level,
                    "link": link,
                    "description": description
                })
        
        return alerts[::-1] # Newest alerts last
    except Exception as e:
        print(f"Parsing Error: {e}")
        return []

def send_to_slack(alert):
    emoji = ":red_circle:" if alert["alert_level"].upper() == "RED" else ":large_orange_circle:"
    
    # Construct a robust message string
    msg_body = (
        f"{emoji} *GDACS {alert['alert_level']} Alert*\n"
        f"*Event:* {alert['title']}\n"
        f"*Country:* {alert['country']}\n"
        f"*Event ID:* {alert['event_id']}"
    )

    payload = {
        "text": f"GDACS {alert['alert_level']} Alert: {alert['title']}",
        "blocks": [
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": msg_body},
                "accessory": {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "View Details"},
                    "url": alert["link"]
                }
            }
        ]
    }

    response = requests.post(
        SLACK_WEBHOOK_URL, 
        data=json.dumps(payload),
        headers={'Content-Type': 'application/json'}
    )
    
    if response.status_code == 200:
        print(f"Successfully posted ID: {alert['event_id']}")
    else:
        print(f"Slack Error {response.status_code}: {response.text}")

if __name__ == "__main__":
    if not SLACK_WEBHOOK_URL:
        print("Error: SLACK_WEBHOOK_URL not set.")
    else:
        last_id = get_last_event_id()
        print(f"Checking for alerts newer than {last_id}...")
        alerts = get_gdacs_alerts(last_id)
        
        if alerts:
            for alert in alerts:
                send_to_slack(alert)
            save_last_event_id(alerts[-1]["event_id"])
        else:
            print("No new alerts found.")
