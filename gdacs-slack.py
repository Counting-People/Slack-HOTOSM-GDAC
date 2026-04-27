import requests
import json
import os
import xml.etree.ElementTree as ET

# Configuration
GDACS_URL = "https://www.gdacs.org/xml/rss.xml"
SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL")
STATE_FILE = "last_event_id.txt"

def get_last_event_id():
    """Reads the last processed event ID from a local file."""
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r") as f:
            return f.read().strip()
    return "0"

def save_last_event_id(event_id):
    """Saves the latest processed event ID to a local file."""
    with open(STATE_FILE, "w") as f:
        f.write(str(event_id))

def get_gdacs_alerts(last_id):
    try:
        response = requests.get(GDACS_URL)
        response.raise_for_status()
        root = ET.fromstring(response.content)
        
        ns = {'gdacs': 'http://www.gdacs.org'}
        alerts = []
        
        for item in root.findall(".//item"):
            event_id = item.find("gdacs:eventid", ns).text if item.find("gdacs:eventid", ns) is not None else "0"
            alert_level = item.find("gdacs:alertlevel", ns).text if item.find("gdacs:alertlevel", ns) is not None else "Green"
            
            # Stop if we hit the last event we already processed
            if event_id == last_id:
                break
                
            if alert_level.upper() in ["ORANGE", "RED"]:
                alerts.append({
                    "title": item.find("title").text,
                    "description": item.find("description").text,
                    "link": item.find("link").text,
                    "country": item.find("gdacs:country", ns).text if item.find("gdacs:country", ns) is not None else "Unknown",
                    "event_id": event_id,
                    "alert_level": alert_level
                })
        
        # Reverse so we process oldest to newest (to keep ID tracking logical)
        return alerts[::-1]
    except Exception as e:
        print(f"Error fetching GDACS data: {e}")
        return []

def send_to_slack(alert):
    emoji = ":red_circle:" if alert["alert_level"].upper() == "RED" else ":large_orange_circle:"
    
    payload = {
        "text": f"GDACS Alert: {alert['title']}",
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
                "text": {"type": "mrkdwn", "text": f"*{alert['title']}*"}
            },
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*Country:*\n{alert['country']}"},
                    {"type": "mrkdwn", "text": f"*Event ID:*\n{alert['event_id']}"}
                ]
            },
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*Details:*\n{alert['description'][:250]}..."},
                "accessory": {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "View Map"},
                    "url": alert["link"]
                }
            },
            {"type": "divider"}
        ]
    }

    response = requests.post(SLACK_WEBHOOK_URL, json=payload)
    if response.status_code != 200:
        print(f"Error: {response.status_code}, {response.text}")
    else:
        print(f"Successfully sent alert: {alert['event_id']}")

if __name__ == "__main__":
    if not SLACK_WEBHOOK_URL:
        print("Error: SLACK_WEBHOOK_URL not set.")
    else:
        last_id = get_last_event_id()
        alerts = get_gdacs_alerts(last_id)
        
        if alerts:
            for alert in alerts:
                send_to_slack(alert)
            # Save the ID of the most recent alert processed
            save_last_event_id(alerts[-1]["event_id"])
        else:
            print("No new Orange/Red alerts found.")
