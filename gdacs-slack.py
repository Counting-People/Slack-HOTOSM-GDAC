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
        
        # Explicit namespace URIs used by GDACS
        GDACS_NS = "{http://www.gdacs.org}"
        
        alerts = []
        for item in root.findall(".//item"):
            # Use bracketed namespace for GDACS tags
            event_id = item.find(f"{GDACS_NS}eventid").text if item.find(f"{GDACS_NS}eventid") is not None else ""
            alert_level = item.find(f"{GDACS_NS}alertlevel").text if item.find(f"{GDACS_NS}alertlevel") is not None else ""
            country = item.find(f"{GDACS_NS}country").text if item.find(f"{GDACS_NS}country") is not None else "Unknown"
            
            # Standard tags (no namespace)
            title = item.find("title").text if item.find("title") is not None else "Unknown Title"
            link = item.find("link").text if item.find("link") is not None else ""
            description = item.find("description").text if item.find("description") is not None else ""

            # Skip if we hit our checkpoint
            if event_id == last_id and last_id != "0":
                break
                
            if alert_level.upper() in ["ORANGE", "RED"]:
                alerts.append({
                    "title": title.strip(),
                    "description": description.strip(),
                    "link": link.strip(),
                    "country": country.strip(),
                    "event_id": event_id.strip(),
                    "alert_level": alert_level.strip()
                })
        
        return alerts[::-1] # Oldest first
    except Exception as e:
        print(f"Error: {e}")
        return []

def send_to_slack(alert):
    emoji = ":red_circle:" if alert["alert_level"].upper() == "RED" else ":large_orange_circle:"
    
    # Ensuring variables are strictly defined to avoid empty ()
    title = alert['title']
    country = alert['country']
    eid = alert['event_id']

    payload = {
        "text": f"New GDACS Alert: {title} ({country})",
        "blocks": [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"{emoji} GDACS {alert['alert_level'].upper()} Alert",
                    "emoji": True
                }
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Event:* {title}\n*Country:* {country}\n*Event ID:* {eid}"
                }
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Details:*\n{alert['description'][:300]}..."
                },
                "accessory": {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "View Details"},
                    "url": alert["link"]
                }
            }
        ]
    }

    response = requests.post(SLACK_WEBHOOK_URL, json=payload)
    if response.status_code == 200:
        print(f"Successfully posted {eid}")
    else:
        print(f"Slack Error {response.status_code}: {response.text}")

if __name__ == "__main__":
    if not SLACK_WEBHOOK_URL:
        print("Missing Webhook URL")
    else:
        last_id = get_last_event_id()
        alerts = get_gdacs_alerts(last_id)
        
        if alerts:
            for alert in alerts:
                send_to_slack(alert)
            save_last_event_id(alerts[-1]["event_id"])
        else:
            print("No new alerts.")
            print("No new alerts found.")
