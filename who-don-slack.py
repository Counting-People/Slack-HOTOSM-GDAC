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
# no way to set a custom color bar like WHO's brand blue here.

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
    # WHO-specific placeholder / blank
