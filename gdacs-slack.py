#!/usr/bin/env python3
"""
GDACS Alert Notifier for HOTOSM Slack
--------------------------------------
Fetches orange and red disaster alerts from the GDACS API and posts new ones
to Slack via a Workflow webhook. All posted events are tracked in
posted_events.json, which is committed back to the repo after each run.

Deduplication key: (event_id, alert_level)
  - A brand-new orange or red event is always posted.
  - If an existing event escalates from orange to red, it is posted again.
  - If an event is unchanged (same event_id, same alert_level), it is skipped.

Modes:
  --initial   Fetch all orange/red alerts from 2026-01-01 to today.
              Triggered via workflow_dispatch with initial_run=true.
  (default)   Nightly run -- makes TWO API calls:
                1. Events whose fromdate falls within the last LOOKBACK_DAYS.
                   Catches brand-new disasters.
                2. Events going back up to EVENTS_WINDOW_DAYS, filtered
                   client-side to those whose datemodified falls within the
                   last LOOKBACK_DAYS. Catches ongoing disasters whose alert
                   level was recently upgraded.
              Results are merged by event_id before processing.
"""

import json
import os
import re
import sys
import requests
from datetime import date, timedelta

# -- Configuration -------------------------------------------------------------

POSTED_EVENTS_FILE = "posted_events.json"
GDACS_API_URL = "https://www.gdacs.org/gdacsapi/api/events/geteventlist/SEARCH"
SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL", "")

INITIAL_FROM_DATE = "2026-01-01"

# Nightly run: how recent a fromdate or datemodified must be to qualify.
# An event is a candidate if EITHER date falls within this window.
LOOKBACK_DAYS = 5

# Nightly run: how far back to query the GDACS API when checking for recently
# modified events. Disasters can stay active for weeks or months, so this window
# needs to be wide enough to retrieve any event that might have been upgraded.
EVENTS_WINDOW_DAYS = 180

ALERT_LEVELS = {"orange", "red"}

# -- Helpers -------------------------------------------------------------------

def posted_key(event_id: str, alert_level: str) -> str:
    """Unique key for a (event_id, alert_level) pair."""
    return f"{event_id}|{alert_level.lower()}"


def strip_html(text: str) -> str:
    """Remove HTML tags from a string."""
    return re.sub(r"<[^>]+>", "", text or "").strip()


# -- State persistence ---------------------------------------------------------

def load_posted_events() -> list:
    """Load the list of previously posted events from the JSON file."""
    if os.path.exists(POSTED_EVENTS_FILE):
        with open(POSTED_EVENTS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def save_posted_events(events: list) -> None:
    """Write the updated list of posted events back to the JSON file."""
    with open(POSTED_EVENTS_FILE, "w", encoding="utf-8") as f:
        json.dump(events, f, indent=2, ensure_ascii=False)
    print(f"[state] Saved {len(events)} total posted events to {POSTED_EVENTS_FILE}")


# -- GDACS API -----------------------------------------------------------------

def fetch_gdacs_events(from_date: str, to_date: str) -> list:
    """
    Fetch orange and red alert events from the GDACS API.
    Paginates automatically until all results are retrieved.
    """
    all_features = []
    page = 1

    while True:
        params = {
            "alertlevel": "Orange,Red",
            "fromdate": from_date,
            "todate": to_date,
            "eventtypes": "EQ,TC,FL,VO,DR,WF",
            "pagesize": 100,
            "pagenumber": page,
        }

        try:
            response = requests.get(GDACS_API_URL, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()
        except Exception as e:
            print(f"[error] GDACS API request failed (page {page}): {e}", file=sys.stderr)
            break

        features = data.get("features", [])
        if not features:
            break

        all_features.extend(features)
        print(f"[gdacs] Fetched page {page}: {len(features)} events")

        if len(features) < 100:
            break  # Last page

        page += 1

    print(f"[gdacs] Total events fetched: {len(all_features)}")
    return all_features


def fetch_nightly_events(today: str) -> list:
    """
    Make two GDACS API calls for the nightly run and merge results by event_id.

    Pass 1 - new events:
        fromdate = today - LOOKBACK_DAYS
        Catches disasters that started recently.

    Pass 2 - recently modified events:
        fromdate = today - EVENTS_WINDOW_DAYS, filtered client-side to
        events whose datemodified >= today - LOOKBACK_DAYS.
        Catches older ongoing disasters whose alert level was just upgraded.
    """
    cutoff_str = (date.today() - timedelta(days=LOOKBACK_DAYS)).strftime("%Y-%m-%d")
    window_str = (date.today() - timedelta(days=EVENTS_WINDOW_DAYS)).strftime("%Y-%m-%d")

    # Pass 1: events whose fromdate is within the last LOOKBACK_DAYS
    print(f"[gdacs] Pass 1 -- events with fromdate >= {cutoff_str}")
    new_features = fetch_gdacs_events(cutoff_str, today)

    # Pass 2: events going back EVENTS_WINDOW_DAYS, then filter by datemodified
    print(f"[gdacs] Pass 2 -- events modified since {cutoff_str} (querying back to {window_str})")
    window_features = fetch_gdacs_events(window_str, today)

    recently_modified = [
        f for f in window_features
        if (f.get("properties", {}).get("datemodified", "") or "") >= cutoff_str
    ]
    print(
        f"[gdacs] Pass 2 filtered to {len(recently_modified)} events "
        f"with datemodified >= {cutoff_str}"
    )

    # Merge both passes, deduplicating by event_id (Pass 1 takes precedence)
    seen_ids: set = set()
    combined: list = []
    for feature in new_features + recently_modified:
        eid = str(feature.get("properties", {}).get("eventid", ""))
        if eid and eid not in seen_ids:
            seen_ids.add(eid)
            combined.append(feature)

    print(f"[gdacs] Combined unique events to process: {len(combined)}")
    return combined


def parse_event(feature: dict) -> dict:
    """Extract and normalise relevant fields from a GDACS GeoJSON feature."""
    props = feature.get("properties", {})

    # Build a clean description -- prefer plain text, fall back to stripping HTML
    description = props.get("description") or strip_html(props.get("htmldescription", ""))

    return {
        "event_id":     str(props.get("eventid", "")),
        "alert_level":  (props.get("alertlevel") or "").capitalize(),
        "event_name":   props.get("name") or props.get("eventname") or "Unknown event",
        "country":      props.get("country", "Unknown"),
        "description":  description,
        "fromdate":     props.get("fromdate", ""),
        "todate":       props.get("todate", ""),
        "datemodified": props.get("datemodified", ""),
    }


# -- Slack ---------------------------------------------------------------------

def post_to_slack(event: dict) -> None:
    """Post an alert to the Slack Workflow webhook."""
    if not SLACK_WEBHOOK_URL:
        raise EnvironmentError("SLACK_WEBHOOK_URL environment variable is not set.")

    level = event["alert_level"].lower()
    emoji = ":red_circle:" if level == "red" else ":large_orange_circle:"

    payload = {
        "event_name":  event["event_name"],
        "country":     event["country"],
        "description": event["description"],
        "event_id":    event["event_id"],
        "alert_level": f"{emoji} {event['alert_level']}",
    }

    response = requests.post(SLACK_WEBHOOK_URL, json=payload, timeout=15)
    response.raise_for_status()


# -- Main ----------------------------------------------------------------------

def main() -> None:
    initial_run = (
        "--initial" in sys.argv
        or os.environ.get("INITIAL_RUN", "").lower() == "true"
    )

    today = date.today().strftime("%Y-%m-%d")

    if initial_run:
        print(f"[run] INITIAL RUN -- fetching all orange/red alerts from {INITIAL_FROM_DATE} to {today}")
        features = fetch_gdacs_events(INITIAL_FROM_DATE, today)
    else:
        print(
            f"[run] Nightly run -- checking fromdate and datemodified "
            f"within last {LOOKBACK_DAYS} days"
        )
        features = fetch_nightly_events(today)

    # Load previously posted events and build a fast-lookup set of posted keys
    posted_events = load_posted_events()
    posted_keys = {
        posted_key(e["event_id"], e["alert_level"])
        for e in posted_events
    }
    print(f"[state] Loaded {len(posted_events)} previously posted events")

    posted_count = 0
    skipped_count = 0
    error_count = 0

    for feature in features:
        event = parse_event(feature)

        # Skip events with no ID or non-qualifying alert levels
        if not event["event_id"]:
            continue
        if event["alert_level"].lower() not in ALERT_LEVELS:
            continue

        key = posted_key(event["event_id"], event["alert_level"])

        if key in posted_keys:
            # Already posted this event at this exact alert level -- no action needed
            skipped_count += 1
            continue

        # This is either a brand-new event, or an escalation (orange -> red)
        try:
            post_to_slack(event)

            # Record the posting with all tracked fields
            record = {
                "event_id":     event["event_id"],
                "alert_level":  event["alert_level"],
                "event_name":   event["event_name"],
                "country":      event["country"],
                "fromdate":     event["fromdate"],
                "todate":       event["todate"],
                "datemodified": event["datemodified"],
                "posted_at":    date.today().isoformat(),
            }
            posted_events.append(record)
            posted_keys.add(key)
            posted_count += 1
            print(
                f"[posted] [{event['alert_level']}] "
                f"ID {event['event_id']} -- {event['event_name']} ({event['country']})"
            )

        except Exception as e:
            error_count += 1
            print(
                f"[error] Failed to post event {event['event_id']}: {e}",
                file=sys.stderr,
            )

    # Always save, even if nothing new was posted (file must exist for git commit)
    save_posted_events(posted_events)

    print(
        f"\n[done] Posted: {posted_count} | "
        f"Already seen (skipped): {skipped_count} | "
        f"Errors: {error_count}"
    )

    if error_count > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
