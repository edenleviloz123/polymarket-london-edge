"""
Analyze Polymarket's own accuracy over time.

For each resolved event (city+date with METAR observation), at each
time-to-close bucket, compute:
  - Did the market's top-priced bucket match the actual winner?
  - How 'confident' was the market (max price across buckets)?
  - How did our model's top bucket (round(consensus)) compare?
"""
import json
import os
import sys
import io
from collections import defaultdict
from statistics import mean, median

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')


def load_jsonl(path):
    if not os.path.exists(path):
        return []
    out = []
    with open(path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return out


def load_json(path):
    if not os.path.exists(path):
        return {}
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


prices = load_jsonl('docs/prices.jsonl')
observations = load_json('docs/observations.json')
forecasts = load_jsonl('docs/forecasts.jsonl')

# Build forecast lookup: (city, date) -> latest consensus value
latest_forecast = {}
for r in forecasts:
    key = (r.get('city') or 'london', r.get('target_date'))
    if None in key:
        continue
    if key not in latest_forecast or r.get('ts', '') > latest_forecast[key].get('ts', ''):
        latest_forecast[key] = r

# Group prices by (city, date, ts_rounded to 10-min) so we get one snapshot per time
# For each snapshot, find the bucket with max yes_price
by_snapshot = defaultdict(dict)  # (city, date, ts_bucket) -> {bucket_label: price_info}
for p in prices:
    city = p.get('city')
    date = p.get('target_date')
    ts = p.get('ts', '')
    # Round ts to 10-min window
    ts_bucket = ts[:15] + '0'  # e.g., '2026-04-20T14:30'
    if not all([city, date, ts]):
        continue
    mtc = p.get('minutes_to_close')
    if mtc is None:
        continue
    key = (city, date, ts_bucket)
    by_snapshot[key][p.get('bucket_label')] = {
        'yes_price': p.get('yes_price') or 0,
        'bucket_temp': p.get('bucket_temp'),
        'bucket_type': p.get('bucket_type'),
        'mtc': mtc,
    }


def bucket_matches_obs(bucket_type, bucket_temp, obs_v):
    if bucket_type == 'single':
        return bucket_temp == obs_v
    if bucket_type == 'below':
        return obs_v <= bucket_temp
    if bucket_type == 'above':
        return obs_v >= bucket_temp
    return False


def timing_of(mtc):
    if mtc >= 480:
        return 'early'
    if mtc >= 60:
        return 'mid'
    return 'late'


print("=" * 70)
print("MARKET vs MODEL — ACCURACY AT EACH TIMING WINDOW")
print("=" * 70)

# Per timing, collect: market_hit, model_hit per snapshot
stats_market = defaultdict(lambda: {'hits': 0, 'total': 0, 'max_prices': []})
stats_model  = defaultdict(lambda: {'hits': 0, 'total': 0})

for (city, date, ts_bucket), buckets in by_snapshot.items():
    if city not in observations or date not in observations[city]:
        continue
    obs_v = observations[city][date]

    # Market's top bucket at this snapshot
    top_label = None
    top_price = -1
    top_bucket_info = None
    for label, info in buckets.items():
        if info['yes_price'] > top_price:
            top_price = info['yes_price']
            top_label = label
            top_bucket_info = info
    if top_bucket_info is None:
        continue

    timing = timing_of(top_bucket_info['mtc'])

    market_hit = bucket_matches_obs(
        top_bucket_info['bucket_type'],
        top_bucket_info['bucket_temp'],
        obs_v
    )
    stats_market[timing]['hits'] += 1 if market_hit else 0
    stats_market[timing]['total'] += 1
    stats_market[timing]['max_prices'].append(top_price)

    # Model's top bucket at this snapshot: round(consensus)
    fc = latest_forecast.get((city, date))
    if fc is None or fc.get('consensus') is None:
        continue
    model_pick = round(fc['consensus'])
    model_hit = (model_pick == obs_v)
    stats_model[timing]['hits'] += 1 if model_hit else 0
    stats_model[timing]['total'] += 1


print(f"\n{'Timing':<10} {'N snap':>8} {'Market hit rate':>18} {'Avg top-price':>16} {'Model hit rate':>17}")
print('-' * 75)
for timing in ['early', 'mid', 'late']:
    m = stats_market[timing]
    if m['total'] == 0:
        continue
    mkt_hit_rate = m['hits'] / m['total']
    avg_top = mean(m['max_prices'])

    mo = stats_model[timing]
    mod_hit_rate = mo['hits'] / mo['total'] if mo['total'] else None
    mod_hit_txt = f"{mod_hit_rate*100:.0f}%" if mod_hit_rate is not None else '—'

    print(f"{timing:<10} {m['total']:>8} {mkt_hit_rate*100:>17.0f}% {avg_top*100:>14.1f}% {mod_hit_txt:>17}")


# ─────────────────────────────────────────────
# Evolution of winner's price — how does it rise?
# ─────────────────────────────────────────────
print("\n")
print("=" * 70)
print("EVOLUTION OF THE WINNING BUCKET'S PRICE")
print("=" * 70)

# For each resolved event, track the winner's price over time
evolution = defaultdict(list)  # (minutes_bucket) -> list of prices

# Group prices by (city, date, bucket) and look up each bucket's actual winner status
for (city, date), fc in latest_forecast.items():
    if city not in observations or date not in observations[city]:
        continue
    obs_v = observations[city][date]
    # Find all price snapshots for this event
    for (c, d, tsb), buckets in by_snapshot.items():
        if c != city or d != date:
            continue
        # Find the winning bucket
        for label, info in buckets.items():
            if not bucket_matches_obs(info['bucket_type'], info['bucket_temp'], obs_v):
                continue
            mtc = info['mtc']
            # Bin by hours-to-close
            if mtc >= 480:
                bin_name = '>8h'
            elif mtc >= 240:
                bin_name = '4-8h'
            elif mtc >= 60:
                bin_name = '1-4h'
            elif mtc >= 15:
                bin_name = '15-60min'
            else:
                bin_name = '<15min'
            evolution[bin_name].append(info['yes_price'])

print(f"\n{'Time to close':<15} {'N':>5} {'Avg winner price':>18} {'Median':>10}")
print('-' * 55)
for bin_name in ['>8h', '4-8h', '1-4h', '15-60min', '<15min']:
    vals = evolution[bin_name]
    if vals:
        print(f"{bin_name:<15} {len(vals):>5} {mean(vals)*100:>16.1f}% {median(vals)*100:>9.1f}%")


# ─────────────────────────────────────────────
# When does the market first 'commit' to the winner?
# ─────────────────────────────────────────────
print("\n")
print("=" * 70)
print("COMMITMENT TO WINNER — WHEN DOES MARKET 'DECIDE'?")
print("=" * 70)

commit_times = []  # minutes-before-close when winner first crosses 50%
for (city, date), fc in latest_forecast.items():
    if city not in observations or date not in observations[city]:
        continue
    obs_v = observations[city][date]
    # Collect winner's price at each snapshot, sorted by mtc descending (most time left first)
    winner_trace = []
    for (c, d, tsb), buckets in by_snapshot.items():
        if c != city or d != date:
            continue
        for label, info in buckets.items():
            if bucket_matches_obs(info['bucket_type'], info['bucket_temp'], obs_v):
                winner_trace.append((info['mtc'], info['yes_price']))
    if not winner_trace:
        continue
    winner_trace.sort(key=lambda x: -x[0])  # start from early

    # Find earliest point where price crossed 50%
    crossed = None
    for mtc, p in winner_trace:
        if p >= 0.5:
            if crossed is None or mtc > crossed:
                crossed = mtc
            else:
                # First threshold crossing — we already found it
                pass
        else:
            # Still below 50% at this point; reset
            crossed = None
    # Actually better: find the first time price stays >=50% until the end
    final_crossing = None
    for i, (mtc, p) in enumerate(winner_trace):
        # Check if from here to end, all prices >= 50
        if all(wp >= 0.5 for _, wp in winner_trace[i:]):
            final_crossing = mtc
            break
    if final_crossing is not None:
        commit_times.append((f"{city} {date}", final_crossing))

print(f"\n{'Event':<22} {'Minutes before close winner locked above 50%':>50}")
print('-' * 75)
for name, t in sorted(commit_times, key=lambda x: -x[1]):
    print(f"{name:<22} {t:>40} min")

if commit_times:
    avgs = [t for _, t in commit_times]
    print(f"\nAverage: {mean(avgs):.0f} min before close")
    print(f"Median:  {median(avgs):.0f} min before close")


# ─────────────────────────────────────────────
# Head-to-head: market vs model per event
# ─────────────────────────────────────────────
print("\n")
print("=" * 70)
print("HEAD-TO-HEAD AT EACH RESOLVED EVENT")
print("=" * 70)

print(f"\n{'Event':<24} {'METAR':<7} {'Model (round)':<15} {'Market @close':<15} {'Winner':<15}")
print('-' * 80)

for (city, date), fc in sorted(latest_forecast.items()):
    if city not in observations or date not in observations[city]:
        continue
    obs_v = observations[city][date]
    model_pick = round(fc['consensus']) if fc.get('consensus') is not None else '?'

    # Market's top pick at closest snapshot to close
    best_snap_mtc = 999999
    best_pick = '?'
    best_price = 0
    for (c, d, tsb), buckets in by_snapshot.items():
        if c != city or d != date:
            continue
        for label, info in buckets.items():
            if info['mtc'] < best_snap_mtc:
                # find top bucket at this snapshot
                tl = max(buckets.items(), key=lambda kv: kv[1]['yes_price'])
                best_snap_mtc = info['mtc']
                best_pick = tl[0]
                best_price = tl[1]['yes_price']

    model_mark = '✓' if model_pick == obs_v else '✗'
    # Market best_pick is a label like "15°C" — extract int to compare
    try:
        import re
        m = re.search(r'(-?\d+)', best_pick)
        market_int = int(m.group(1)) if m else None
    except Exception:
        market_int = None
    market_mark = '✓' if market_int == obs_v else '✗'

    event_label = f"{city} {date}"
    print(f"{event_label:<24} {obs_v}°C   {str(model_pick)+'°C':<14} {model_mark} "
          f"{best_pick:<14} {market_mark} @ {best_price*100:.0f}%")
