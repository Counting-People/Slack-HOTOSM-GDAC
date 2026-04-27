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
        
        # Literal URI for GDACS namespace
        GNS = "{http://www.gdacs.org}"
        
        alerts = []
        for item in root.findall(".//item"):
            # Extraction
            event_id = item.find(f"{GNS}eventid").text if item.find(f"{GNS}eventid") is not None else ""
            alert_level = item.find(f"{GNS}alertlevel").text if item.find(f"{GNS}alertlevel") is not None else "Green"
            country = item.find(f"{GNS}country").text if item.find(f"{GNS}country") is not None else "Unknown"
            title = item.find("title").text if item.find("title") is not None else "No Title"
            link = item.find("link").text if item.find("link") is not None else "https://www.gdacs.org"

            # Checkpoint logic
            if event_id == last_id and last_id != "0":
                break
                
            if alert_level.upper() in ["ORANGE", "RED"]:
                alerts.append({
                    "title": title.strip(),
                    "country": country.strip(),
                    "event_id": event_id.strip(),
                    "alert_level": alert_level.strip(),
                    "link": link.strip()
                })
        
        return alerts[::-1] 
    except Exception as e:
        print(f"Extraction Error: {e}")
        return []

def send_to_slack(alert):
    emoji = ":red_circle:" if alert["alert_level"].upper() == "RED" else ":large_orange_circle:"
    
    # CRITICAL: If blocks fail, this fallback MUST contain the data.
    fallback_message = f"{emoji} *GDACS {alert['alert_level']} Alert*: {alert['title']} in {alert['country']} (ID: {alert['event_id']})"

    payload = {
        "text": fallback_message,
        "blocks": [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": fallback_message
                },
                "accessory": {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "View Map"},
                    "url": alert["link"]
                }
            }
        ]
    }

    # Posting with explicit JSON header
    response = requests.post(
        SLACK_WEBHOOK_URL, 
        data=json.dumps(payload),
        headers={'Content-Type': 'application/json'}
    )
    
    if response.status_code == 200:
        print(f"Successfully posted {alert['event_id']}")
    else:
        print(f"Error {response.status_code}: {response.text}")

if __name__ == "__main__":
    if not SLACK_WEBHOOK_URL:
        print("No Webhook URL found")
    else:
        last_id = get_last_event_id()
        alerts = get_gdacs_alerts(last_id)
        if alerts:
            for alert in alerts:
                send_to_slack(alert)
            save_last_event_id(alerts[-1]["event_id"])
        else:
            print("No new alerts found.")
