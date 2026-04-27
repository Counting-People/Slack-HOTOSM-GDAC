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
        
        # Parse the XML
        root = ET.fromstring(response.content)
        
        # Define all possible namespaces found in GDACS RSS
        ns = {
            'gdacs': 'http://www.gdacs.org',
            'geo': 'http://www.w3.org/2003/01/geo/wgs84_pos#',
            'dc': 'http://purl.org/dc/elements/1.1/'
        }
        
        alerts = []
        for item in root.findall(".//item"):
            # Robust extraction: checks for namespace, then falls back to local name
            def find_text(tag_name):
                # Try with namespace
                element = item.find(f"gdacs:{tag_name}", ns)
                if element is None:
                    # Try without namespace
                    element = item.find(tag_name)
                return element.text.strip() if element is not None and element.text else ""

            event_id = find_text("eventid")
            alert_level = find_text("alertlevel")
            country = find_text("country")
            
            # Standard RSS tags don't use the gdacs namespace
            title_el = item.find("title")
            title = title_el.text.strip() if title_el is not None else "Unknown Event"
            
            link_el = item.find("link")
            link = link_el.text.strip() if link_el is not None else ""
            
            desc_el = item.find("description")
            description = desc_el.text.strip() if desc_el is not None else ""

            # Debugging check: If event_id is still empty, the parser is failing
            if not event_id:
                continue

            # Stop at the last processed ID
            if event_id == last_id and last_id != "0":
                break
                
            if alert_level.upper() in ["ORANGE", "RED"]:
                alerts.append({
                    "title": title,
                    "description": description,
                    "link": link,
                    "country": country,
                    "event_id": event_id,
                    "alert_level": alert_level
                })
        
        return alerts[::-1] # Oldest to newest
    except Exception as e:
        print(f"CRITICAL ERROR: {e}")
        return []

def send_to_slack(alert):
    emoji = ":red_circle:" if alert["alert_level"].upper() == "RED" else ":large_orange_circle:"
    
    # We use .get() or "Unknown" to ensure no empty parentheses
    t = alert.get('title') or "Unknown Title"
    c = alert.get('country') or "Unknown Country"
    i = alert.get('event_id') or "No ID"

    payload = {
        "text": f"New GDACS Alert: {t} ({c}) - ID: {i}",
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
                    "text": f"*Event:* {t}\n*Country:* {c}\n*Event ID:* {i}"
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
                    "url": alert["link"] or "https://www.gdacs.org"
                }
            }
        ]
    }

    response = requests.post(SLACK_WEBHOOK_URL, json=payload)
    if response.status_code != 200:
        print(f"SLACK ERROR: {response.status_code} - {response.text}")
    else:
        print(f"SUCCESS: Posted event {i}")

if __name__ == "__main__":
    if not SLACK_WEBHOOK_URL:
        print("WEBHOOK URL MISSING")
    else:
        last_id = get_last_event_id()
        print(f"Checking for alerts newer than: {last_id}")
        alerts = get_gdacs_alerts(last_id)
        
        if alerts:
            for alert in alerts:
                send_to_slack(alert)
            save_last_event_id(alerts[-1]["event_id"])
            print(f"Saved new last_id: {alerts[-1]['event_id']}")
        else:
            print("No new alerts found.")
