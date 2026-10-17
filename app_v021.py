#!/usr/bin/env python3
"""Fantasy Decision Lab v0.2.1 hotfix: resilient FantasyPros Compare requests."""
from __future__ import annotations
from datetime import datetime, timezone
import app_v02 as app

core = app.core
app.APP_VERSION = '0.2.1'


def resilient_fetch_pair_and_cache(position: str, aid: str, bid: str, force: bool = False):
    key = core.get_api_key()
    if not key:
        raise RuntimeError(
            'FantasyPros API key is not configured. Double-click First-time Setup.command in the app folder.'
        )

    live_cache = core.CACHE_ROOT / position / 'compare_cache'
    live_cache.mkdir(parents=True, exist_ok=True)
    ids = sorted([str(aid), str(bid)])
    cache = live_cache / f'compare_{ids[0]}_{ids[1]}.json'
    if cache.exists() and not force:
        return cache

    params = {
        'players': f'{aid}:{bid}',
        'position': position,
        'year': core.YEAR,
        'week': core.WEEK,
        'ranking_type': 'weekly',
        'details': 'all',
    }

    # FantasyPros occasionally returns a temporary CDN/gateway error. Treat
    # 502/503/504 the same way we already treat rate limiting: wait and retry.
    waits = [2, 4, 8, 12, 16]
    last_error = None
    for attempt, wait_seconds in enumerate(waits, start=1):
        try:
            r = core.requests.get(
                core.COMPARE_URL,
                params=params,
                headers={'x-api-key': key},
                timeout=30,
            )
            if r.status_code == 200:
                cache.write_text(core.json.dumps(r.json(), indent=2), encoding='utf-8')
                return cache

            if r.status_code in {429, 502, 503, 504}:
                last_error = f'HTTP {r.status_code}'
                if attempt < len(waits):
                    core.time.sleep(wait_seconds)
                    continue
                break

            raise RuntimeError(
                f'FantasyPros Compare request failed with HTTP {r.status_code}: {r.text[:200]}'
            )
        except core.requests.RequestException as exc:
            last_error = str(exc)
            if attempt < len(waits):
                core.time.sleep(wait_seconds)
                continue
            break

    raise RuntimeError(
        'FantasyPros is temporarily unavailable after several automatic retries'
        + (f' ({last_error}).' if last_error else '.')
        + ' Please try the comparison again in a minute.'
    )


def scoring_aware_last_refreshed(position: str, aid: str, bid: str):
    scoring_key = 'STD' if position == 'QB' else core.SCORING
    newest = None
    for path, data in core.iter_json_payloads(position):
        try:
            bucket = (data.get('rankings') or {}).get(scoring_key) or {}
            if str(aid) in bucket and str(bid) in bucket:
                mt = path.stat().st_mtime
                newest = mt if newest is None else max(newest, mt)
        except Exception:
            continue
    if newest is None:
        return None
    return datetime.fromtimestamp(newest, tz=timezone.utc).astimezone().isoformat(timespec='seconds')


core.fetch_pair_and_cache = resilient_fetch_pair_and_cache
core.matchup_last_refreshed = scoring_aware_last_refreshed


if __name__ == '__main__':
    app.main()
