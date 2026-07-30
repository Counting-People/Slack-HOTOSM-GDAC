import os
import json
import re
import time
import requests
from datetime import datetime, timedelta, timezone

SLACK_WEBHOOK_URL = os.environ['SLACK_WEBHOOK_URL']

# Set DRY_RUN=true (as a workflow env var) to preview what would be posted
# without actually sending anything to Slack and without updating
# posted_dons.json.
DRY_RUN = os.environ.get('DRY_RUN', 'false').lower() == 'true'

API_URL = 'https://www.who.int/api/news/diseaseoutbreaknews'
STATE_FILE = 'posted_dons.json'

# Note: Workflow Builder webhooks are plain text/variables only — there's
# no way to set a custom color bar like WHO's brand blue (#009EDB) here.
# The closest available substitute is the blue circle emoji below.

# Only look at DONs published in the last N days, to avoid re-scanning
# the entire historical archive (which goes back to 1996) every run.
# TEMPORARY: 210 days covers back to January 1, 2026, for initial testing.
# Reset to 30 once the test run looks correct.
LOOKBACK_DAYS = 210


def load_posted_ids():
    try:
        with open(STATE_FILE, 'r') as f:
            return set(json.load(f))
    except (FileNotFoundError, json.JSONDecodeError):
        return set()


def save_posted_ids(ids):
    with open(STATE_FILE, 'w') as f:
        json.dump(sorted(ids), f, indent=2)


def strip_html(html):
    if not html:
        return ''
    text = re.sub(r'<[^>]+>', ' ', html)
    text = text.replace('&nbsp;', ' ').replace('&rsquo;', "'").replace('&ndash;', '-')
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def post_to_slack(item):
    title = item.get('OverrideTitle') or item.get('Title') or 'Untitled DON'
    url_name = item.get('UrlName', '')
    don_url = f'https://www.who.int/emergencies/disease-outbreak-news/item/{url_name}'
    pub_date = item.get('PublicationDateAndTime', item.get('PublicationDate', ''))[:10]
    summary = strip_html(item.get('Summary') or item.get('Overview', ''))[:300]
    if len(summary) == 300:
        summary += '...'
    don_id = item.get('DonId') or item.get('Id', '')

    # Reuses the SAME variable names already declared in Workflow Builder
    # for the GDACS alerts, so no changes are needed on the Slack side.
    # DONs have no severity level and no single reliable country field
    # (some cover a region or multiple countries), so those two get a
    # WHO-specific placeholder / blank instead.
    payload = {
        "event_name":  title,
        "country":     "",  # DONs don't have a consistent single-country field
        "description": f"{pub_date} \u2014 {summary}",
        "event_id":    don_id,
        "alert_level": ":large_blue_circle: WHO Disease Outbreak News",
        "event_url":   don_url,
    }

    if DRY_RUN:
        print("--- DRY RUN: would post ---")
        print(json.dumps(payload, indent=2))
        print("---------------------------")
        return "DRY_RUN"

    r = requests.post(SLACK_WEBHOOK_URL, json=payload)
    if r.status_code != 200:
        print(f"Slack error {r.status_code}: {r.text}")
    return r.status_code


def main():
    resp = requests.get(API_URL, timeout=30)
    if resp.status_code != 200:
        print(f"WHO API error: {resp.status_code}")
        return

    data = resp.json()
    items = data.get('value', [])

    cutoff = datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)

    recent_items = []
    for item in items:
        pub_str = item.get('PublicationDateAndTime') or item.get('PublicationDate')
        if not pub_str:
            continue
        try:
            pub_dt = datetime.fromisoformat(pub_str.replace('Z', '+00:00'))
        except ValueError:
            continue
        if pub_dt >= cutoff:
            recent_items.append(item)

    posted_ids = load_posted_ids()
    new_count = 0

    for item in recent_items:
        # DonId is the stable identifier when present; fall back to the
        # internal Id (a permanent guid) for older entries where DonId is blank.
        dedup_key = item.get('DonId') or item.get('Id')
        if not dedup_key or dedup_key in posted_ids:
            continue

        status = post_to_slack(item)
        print(f"Posted {dedup_key}: {status}")
        posted_ids.add(dedup_key)
        new_count += 1
        time.sleep(1)  # avoid Slack rate limiting

    if DRY_RUN:
        print(f"Checked {len(recent_items)} recent DONs, would post {new_count} new (DRY_RUN, state not saved)")
    else:
        save_posted_ids(posted_ids)
        print(f"Checked {len(recent_items)} recent DONs, posted {new_count} new")


if __name__ == '__main__':
    main()
