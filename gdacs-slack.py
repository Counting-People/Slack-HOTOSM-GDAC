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
        response = requests.get(GDACS_URL)
        response.raise_for_status()
        root = ET.fromstring(response.content)
        
        # GDACS uses specific XML namespaces
        ns = {
            'gdacs': 'http://www.gdacs.org',
            'geo': 'http://www.w3.org/2003/01/geo/wgs84_pos#',
            'as': 'http://purl.org/atompub/syndication/1.0/'
        }
        
        alerts = []
        for item in root.findall(".//item"):
            # Extracting with namespace handling
            event_id = item.find("gdacs:eventid", ns).text if item.find("gdacs:eventid", ns) is not None else "0"
            alert_level = item.find("gdacs:alertlevel", ns).text if item.find("gdacs:alertlevel", ns) is not None else "Green"
            
            # Stop if we reach the last processed event
            if event_id == last_id and last_id != "0":
                break
                
            if alert_level.upper() in ["ORANGE", "RED"]:
                alerts.append({
                    "title": item.find("title").text,
                    "description": item.find("description").text.strip() if item.find("description") is not None else "",
                    "link": item.find("link").text,
                    "country": item.find("gdacs:country", ns).text if item.find("gdacs:country", ns) is not None else "Unknown",
                    "event_id": event_id,
                    "alert_level": alert_level
                })
        
        return alerts[::-1] # Oldest to newest
    except Exception as e:
        print(f"Error parsing GDACS RSS: {e}")
        return []

def send_to_slack(alert):
    emoji = ":red_circle:" if alert["alert_level"].upper() == "RED" else ":large_orange_circle:"
    
    # Clean description to prevent Slack parsing errors (max 3000 chars, but let's keep it safe at 500)
    clean_desc = (alert['description'][:500] + '...') if len(alert['description']) > 500 else alert['description']

    payload = {
        "text": f"New GDACS Alert: {alert['title']}", # Notification fallback
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
                "text": {"type": "mrkdwn", "text": f"*Details:*\n{clean_desc}"},
                "accessory": {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "View Details"},
                    "url": alert["link"]
                }
            }
        ]
    }

    # CRITICAL: Use json= parameter to ensure correct header/encoding
    response = requests.post(SLACK_WEBHOOK_URL, json=payload)
    
    if response.status_code != 200:
        print(f"SLACK ERROR: {response.status_code} - {response.text}")
        # Debug: Print the payload if it fails so you can see it in GitHub logs
        print(f"FAILED PAYLOAD: {json.dumps(payload)}")
    else:
        print(f"Successfully posted event {alert['event_id']}")

if __name__ == "__main__":
    if not SLACK_WEBHOOK_URL:
        print("Missing SLACK_WEBHOOK_URL")
    else:
        last_id = get_last_event_id()
        print(f"Checking for alerts newer than ID: {last_id}")
        
        alerts = get_gdacs_alerts(last_id)
        
        if alerts:
            for alert in alerts:
                send_to_slack(alert)
            save_last_event_id(alerts[-1]["event_id"])
            print(f"Updated last_event_id to {alerts[-1]['event_id']}")
        else:
            print("No new alerts found.")
