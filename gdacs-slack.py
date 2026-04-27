import requests
import json
import os

# GDACS RSS Feed URL (Orange and Red alerts)
GDACS_URL = "https://www.gdacs.org/xml/rss.xml"
SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL")

def get_gdacs_alerts():
    """Fetches alerts from GDACS RSS feed."""
    try:
        import xml.etree.ElementTree as ET
        response = requests.get(GDACS_URL)
        response.raise_for_status()
        root = ET.fromstring(response.content)
        
        alerts = []
        for item in root.findall(".//item"):
            alert = {
                "title": item.find("title").text,
                "description": item.find("description").text,
                "link": item.find("link").text,
                "country": item.find("{http://www.gdacs.org}country").text if item.find("{http://www.gdacs.org}country") is not None else "Unknown",
                "event_id": item.find("{http://www.gdacs.org}eventid").text if item.find("{http://www.gdacs.org}eventid") is not None else "N/A",
                "alert_level": item.find("{http://www.gdacs.org}alertlevel").text if item.find("{http://www.gdacs.org}alertlevel") is not None else "Green"
            }
            # We focus on Orange and Red for this workflow
            if alert["alert_level"].upper() in ["ORANGE", "RED"]:
                alerts.append(alert)
        return alerts
    except Exception as e:
        print(f"Error fetching GDACS data: {e}")
        return []

def send_to_slack(alert):
    """Sends a formatted Block Kit message to Slack."""
    emoji = ":red_circle:" if alert["alert_level"].upper() == "RED" else ":large_orange_circle:"
    
    payload = {
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
                    {
                        "type": "mrkdwn",
                        "text": f"*Country:*\n{alert['country']}"
                    },
                    {
                        "type": "mrkdwn",
                        "text": f"*Event ID:*\n{alert['event_id']}"
                    }
                ]
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Details:*\n{alert['description']}"
                },
                "accessory": {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": "View Map",
                        "emoji": True
                    },
                    "url": alert["link"],
                    "action_id": "button-action"
                }
            },
            {
                "type": "divider"
            }
        ]
    }

    print(f"DEBUG PAYLOAD: {alert['title']}") # Keep simple logs for GitHub Actions
    response = requests.post(
        SLACK_WEBHOOK_URL, 
        data=json.dumps(payload),
        headers={'Content-Type': 'application/json'}
    )
    
    if response.status_code != 200:
        print(f"Error sending to Slack: {response.status_code}, {response.text}")

if __name__ == "__main__":
    if not SLACK_WEBHOOK_URL:
        print("Error: SLACK_WEBHOOK_URL environment variable not set.")
    else:
        alerts = get_gdacs_alerts()
        for alert in alerts:
            send_to_slack(alert)
