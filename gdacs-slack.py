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
        
        # DEFINITIVE NAMESPACE MAP
        ns = {
            'gdacs': 'http://www.gdacs.org',
            'geo': 'http://www.w3.org/2003/01/geo/wgs84_pos#',
            'dc': 'http://purl.org/dc/elements/1.1/'
        }
        
        alerts = []
        for item in root.findall(".//item"):
            # Use the namespace map 'ns' for EVERY gdacs-specific tag
            event_id = item.find("gdacs:eventid", ns).text if item.find("gdacs:eventid", ns) is not None else "UnknownID"
            alert_level = item.find("gdacs:alertlevel", ns).text if item.find("gdacs:alertlevel", ns) is not None else "Green"
            country = item.find("gdacs:country", ns).text if item.find("gdacs:country", ns) is not None else "Unknown Country"
            title = item.find("title").text if item.find("title") is not None else "No Title"
            
            # Stop at the last processed ID
            if event_id == last_id and last_id != "0":
                break
                
            if alert_level.upper() in ["ORANGE", "RED"]:
                alerts.append({
                    "title": title,
                    "description": item.find("description").text.strip() if item.find("description") is not None else "",
                    "link": item.find("link").text if item.find("link") is not None else "",
                    "country": country,
                    "event_id": event_id,
                    "alert_level": alert_level
                })
        
        return alerts[::-1] # Process oldest to newest
    except Exception as e:
        print(f"Error parsing XML: {e}")
        return []

def send_to_slack(alert):
    emoji = ":red_circle:" if alert["alert_level"].upper() == "RED" else ":large_orange_circle:"
    
    # This matches the "New GDACS Alert: () -" text you saw. 
    # I've reinforced the variable placement here.
    fallback_text = f"New GDACS Alert: {alert['title']} ({alert['country']}) - ID: {alert['event_id']}"

    payload = {
        "text": fallback_text,
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
                    "text": f"*Title:* {alert['title']}\n*Country:* {alert['country']}\n*Event ID:* {alert['event_id']}"
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
    if response.status_code != 200:
        print(f"SLACK ERROR: {response.text}")
    else:
        print(f"SUCCESS: Posted {alert['event_id']}")

if __name__ == "__main__":
    if not SLACK_WEBHOOK_URL:
        print("WEBHOOK URL MISSING")
    else:
        last_id = get_last_event_id()
        alerts = get_gdacs_alerts(last_id)
        
        if alerts:
            for alert in alerts:
                send_to_slack(alert)
            save_last_event_id(alerts[-1]["event_id"])
        else:
            print("No new Orange/Red alerts found.")
