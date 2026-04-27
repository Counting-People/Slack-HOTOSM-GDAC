import requests
import json
import os
import xml.etree.ElementTree as ET

# GDACS RSS Feed URL
GDACS_URL = "https://www.gdacs.org/xml/rss.xml"
SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL")

def get_gdacs_alerts():
    try:
        response = requests.get(GDACS_URL)
        response.raise_for_status()
        root = ET.fromstring(response.content)
        
        # Namespace mapping for GDACS tags
        ns = {'gdacs': 'http://www.gdacs.org'}
        
        alerts = []
        for item in root.findall(".//item"):
            alert = {
                "title": item.find("title").text,
                "description": item.find("description").text,
                "link": item.find("link").text,
                "country": item.find("gdacs:country", ns).text if item.find("gdacs:country", ns) is not None else "Unknown",
                "event_id": item.find("gdacs:eventid", ns).text if item.find("gdacs:eventid", ns) is not None else "N/A",
                "alert_level": item.find("gdacs:alertlevel", ns).text if item.find("gdacs:alertlevel", ns) is not None else "Green"
            }
            if alert["alert_level"].upper() in ["ORANGE", "RED"]:
                alerts.append(alert)
        return alerts
    except Exception as e:
        print(f"Error fetching GDACS data: {e}")
        return []

def send_to_slack(alert):
    emoji = ":red_circle:" if alert["alert_level"].upper() == "RED" else ":large_orange_circle:"
    
    # Constructing the Block Kit payload
    payload = {
        "text": f"GDACS Alert: {alert['title']}", # Fallback text for notifications
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
                    "text": f"*{alert['title']}*"
                }
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
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Details:*\n{alert['description'][:250]}..." # Slack limit safeguard
                },
                "accessory": {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "View Map"},
                    "url": alert["link"]
                }
            },
            {"type": "divider"}
        ]
    }

    # CRITICAL: Use json=payload to ensure correct Content-Type and encoding
    response = requests.post(SLACK_WEBHOOK_URL, json=payload)
    
    if response.status_code != 200:
        print(f"DEBUG: Failed to send {alert['event_id']}. Status: {response.status_code}, Response: {response.text}")
    else:
        print(f"DEBUG PAYLOAD SENT: {alert['title']}")

if __name__ == "__main__":
    if not SLACK_WEBHOOK_URL:
        print("Error: SLACK_WEBHOOK_URL not found.")
    else:
        alerts = get_gdacs_alerts()
        for alert in alerts:
            send_to_slack(alert)
