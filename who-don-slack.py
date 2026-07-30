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

# Only look at DONs published after this cutoff. Two ways to control it:
#   - START_DATE env var: an actual calendar date, e.g. "2026-01-01"
#     (takes priority if set — no need to calculate day-counts)
#   - LOOKBACK_DAYS env var: a rolling N-days-back window (default 30)
_start_date_str = os.environ.get('START_DATE', '').strip()
if _start_date_str:
    CUTOFF_DATE = datetime.fromisoformat(_start_date_str).replace(tzinfo=timezone.utc)
else:
    LOOKBACK_DAYS = int(os.environ.get('LOOKBACK_DAYS', '30'))
    CUTOFF_DATE = None  # computed fresh at run time in main() from LOOKBACK_DAYS


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


def build_don_url(item):
    url_name = item.get('UrlName', '')
    if url_name:
        return f'https://www.who.int/emergencies/disease-outbreak-news/item/{url_name}'
    default_url = item.get('ItemDefaultUrl', '')
    if default_url.startswith('http'):
        return default_url
    if default_url.startswith('/'):
        return f'https://www.who.int{default_url}'
    return 'https://www.who.int/emergencies/disease-outbreak-news'


def post_to_slack(item):
    title = item.get('OverrideTitle') or item.get('Title') or 'Untitled DON'
    don_url = build_don_url(item)
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
        "event_name":  f"{pub_date} \u2014 {title}",
        "country":     "",  # DONs don't have a consistent single-country field
        "description": summary,
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


def fetch_all_recent_items(cutoff):
    """
    The WHO API defaults to returning the OLDEST records first, paginated
    at ~50 per page. We request newest-first via $orderby and page through
    until we hit items older than our cutoff.

    Fallback: some OData-style endpoints silently ignore $orderby. If the
    very first item we get back is still ancient (well past the cutoff),
    we instead fetch the total record count and jump straight to the last
    page, which will hold the newest records under the default (ascending)
    ordering.
    """
    def get_page(params):
        resp = requests.get(API_URL, params=params, timeout=30)
        if resp.status_code != 200:
            print(f"WHO API error: {resp.status_code}")
            return None
        data = resp.json()
        return data if isinstance(data, list) else data.get('value', [])

    def parse_date(item):
        pub_str = item.get('PublicationDateAndTime') or item.get('PublicationDate')
        if not pub_str:
            return None
        try:
            return datetime.fromisoformat(pub_str.replace('Z', '+00:00'))
        except ValueError:
            return None

    page_size = 100

    # First attempt: request newest-first directly.
    first_page = get_page({'$orderby': 'PublicationDate desc', '$top': page_size, '$skip': 0})
    if first_page is None:
        return []
    print(f"DEBUG: first_page length = {len(first_page)}")

    if first_page:
        first_date = parse_date(first_page[0])
        print(f"DEBUG: first item date = {first_date}, cutoff = {cutoff}")

        if first_date and first_date >= cutoff:
            print("DEBUG: using $orderby forward-paging path")
            # $orderby worked as expected — page forward normally.
            recent_items = []
            skip = 0
            items = first_page
            page_num = 1
            while items:
                hit_old_item = False
                for item in items:
                    d = parse_date(item)
                    if d is None:
                        continue
                    if d >= cutoff:
                        recent_items.append(item)
                    else:
                        hit_old_item = True
                print(f"DEBUG: page {page_num} had {len(items)} items, running recent_items total = {len(recent_items)}, hit_old_item = {hit_old_item}")
                if hit_old_item or len(items) < page_size:
                    break
                skip += page_size
                page_num += 1
                items = get_page({'$orderby': 'PublicationDate desc', '$top': page_size, '$skip': skip})
                if items is None:
                    break
            return recent_items

    # Fallback: $orderby was ignored (or had no effect) — get total count
    # and jump to the final page(s), where the newest records live under
    # the default ascending order.
    count_resp = requests.get(f"{API_URL}/$count", timeout=30)
    if count_resp.status_code != 200:
        print(f"WHO API error: could not get total count, status {count_resp.status_code}")
        return []
    try:
        total_count = int(count_resp.text.strip())
    except ValueError:
        print(f"WHO API error: unexpected $count response: {count_resp.text[:200]}")
        return []

    recent_items = []
    skip = max(0, total_count - page_size)
    while True:
        items = get_page({'$top': page_size, '$skip': skip})
        if not items:
            break
        for item in items:
            d = parse_date(item)
            if d and d >= cutoff:
                recent_items.append(item)
        if skip == 0:
            break
        skip = max(0, skip - page_size)

    return recent_items


def main():
    cutoff = CUTOFF_DATE if CUTOFF_DATE else datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)
    print(f"DEBUG: START_DATE env = '{os.environ.get('START_DATE', '')}', LOOKBACK_DAYS env = '{os.environ.get('LOOKBACK_DAYS', '')}', computed cutoff = {cutoff}")
    recent_items = fetch_all_recent_items(cutoff)

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
