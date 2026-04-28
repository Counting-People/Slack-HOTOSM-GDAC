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
        for item in root.findall(".//item"):
            # The most aggressive way to find tags: ignoring namespaces entirely
            event_id = next((child.text for child in item if 'eventid' in child.tag), "0")
            alert_level = next((child.text for child in item if 'alertlevel' in child.tag), "Green")
            country = next((child.text for child in item if 'country' in child.tag), "Unknown")
            title = item.findtext("title") or "No Title"

            if event_id == last_id and last_id != "0":
                break
                
            if alert_level.upper() in ["ORANGE", "RED"]:
                alerts.append({
                    "title": str(title).strip(),
                    "country": str(country).strip(),
                    "event_id": str(event_id).strip(),
                    "alert_level": str(alert_level).strip()
                })
        
        return alerts[::-1]
    except Exception as e:
        print(f"Error: {e}")
        return []

def send_to_slack(alert):
    # Construct a PLAIN STRING. No blocks, no dictionaries.
    # If this shows up as "()", it means the variables themselves are literal empty strings.
    
    text_output = "GDACS ALERT: " + alert['title'] + " in " + alert['country'] + " (ID: " + alert['event_id'] + ")"
    
    print(f"LOGGING OUTPUT STRING: {text_output}")
    
    payload = {"text": text_output}

    response = requests.post(
        SLACK_WEBHOOK_URL, 
        data=json.dumps(payload),
        headers={'Content-Type': 'application/json'}
    )
    
    if response.status_code != 200:
        print(f"Slack Error: {response.text}")

if __name__ == "__main__":
    if not SLACK_WEBHOOK_URL:
        print("Missing Webhook")
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
            
