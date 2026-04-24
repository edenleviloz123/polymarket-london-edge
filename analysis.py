"""
Comprehensive analysis of the sample so far. One-shot script that reads
all state files in docs/ and prints detailed findings.
"""
import json
import os
import sys
import io
from collections import defaultdict
from statistics import mean, median, stdev

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

def load_jsonl(path):
    if not os.path.exists(path): return []
    out = []
    with open(path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line:
                try: out.append(json.loads(line))
                except: pass
    return out

def load_json(path):
    if not os.path.exists(path): return {}
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except:
        return {}

def header(t):
    print(f"\n{'='*70}\n{t}\n{'='*70}")

def subheader(t):
    print(f"\n{'-'*50}\n{t}\n{'-'*50}")

forecasts = load_jsonl('docs/forecasts.jsonl')
signals = load_jsonl('docs/signals.jsonl')
prices = load_jsonl('docs/prices.jsonl')
observations = load_json('docs/observations.json')
accuracy = load_json('docs/accuracy.json')

# ─────────────────────────────────────────────────────
# Sample scope
# ─────────────────────────────────────────────────────
header("SAMPLE SCOPE")
print(f"Forecasts logged:  {len(forecasts)}")
print(f"Signals recorded:  {len(signals)}")
print(f"Price snapshots:   {len(prices)}")
print(f"Cities observed:   {list(observations.keys())}")
days_observed = {}
for city, d in observations.items():
    days_observed[city] = sorted(d.keys())
    print(f"  {city}: {len(d)} days — {list(d.keys())[:3]}...{list(d.keys())[-3:]}")

# ─────────────────────────────────────────────────────
# Per-model accuracy ACROSS ALL DAYS AND CITIES
# ─────────────────────────────────────────────────────
header("MODEL ACCURACY — ALL DAYS AND CITIES")

# Build latest forecast per (city, target_date)
latest = {}
for r in forecasts:
    key = (r.get('city') or 'london', r.get('target_date'))
    if None in key: continue
    if key not in latest or r.get('ts', '') > latest[key].get('ts', ''):
        latest[key] = r

print(f"\nUnique (city, date) forecast rows: {len(latest)}")

MODELS = ['MeteoFrance', 'ICON', 'GFS', 'UKMO', 'ECMWF']

model_errors = {m: [] for m in MODELS}
model_bucket_hits = {m: [] for m in MODELS}
cons_errors = []
cons_bucket_hits = []

per_city_errors = {}
per_city_bucket_hits = {}

for (city, date), r in latest.items():
    if city not in observations or date not in observations[city]:
        continue
    obs_v = observations[city][date]
    per_city_errors.setdefault(city, {m: [] for m in MODELS})
    per_city_bucket_hits.setdefault(city, {m: [] for m in MODELS})

    for m, v in (r.get('models') or {}).items():
        if v is None or m not in MODELS: continue
        err = v - obs_v
        model_errors[m].append(err)
        model_bucket_hits[m].append(round(v) == obs_v)
        per_city_errors[city][m].append(err)
        per_city_bucket_hits[city][m].append(round(v) == obs_v)

    cm = r.get('consensus')
    if cm is not None:
        cons_errors.append(cm - obs_v)
        cons_bucket_hits.append(round(cm) == obs_v)

def score(errs, hits):
    if not errs: return None
    mae = mean(abs(e) for e in errs)
    bias = mean(errs)
    sd = stdev(errs) if len(errs) > 1 else 0
    hit_rate = mean(1 if h else 0 for h in hits) if hits else 0
    return (mae, bias, sd, hit_rate, len(errs))

print(f"\n{'Model':<14} {'MAE':>6} {'Bias':>7} {'StdDev':>8} {'BucketHit':>10} {'N':>4}")
print('-' * 60)
for m in MODELS:
    s = score(model_errors[m], model_bucket_hits[m])
    if s:
        print(f"{m:<14} {s[0]:>5.2f}° {s[1]:>+6.2f}° {s[2]:>7.2f}° {s[3]*100:>9.0f}% {s[4]:>4}")

if cons_errors:
    s = score(cons_errors, cons_bucket_hits)
    print(f"{'Consensus':<14} {s[0]:>5.2f}° {s[1]:>+6.2f}° {s[2]:>7.2f}° {s[3]*100:>9.0f}% {s[4]:>4}")

# ─────────────────────────────────────────────────────
# Per-city breakdown
# ─────────────────────────────────────────────────────
for city in per_city_errors:
    subheader(f"BREAKDOWN — {city.upper()}")
    print(f"\n{'Model':<14} {'MAE':>6} {'Bias':>7} {'BucketHit':>10} {'N':>4}")
    for m in MODELS:
        s = score(per_city_errors[city][m], per_city_bucket_hits[city][m])
        if s:
            print(f"{m:<14} {s[0]:>5.2f}° {s[1]:>+6.2f}° {s[3]*100:>9.0f}% {s[4]:>4}")

# ─────────────────────────────────────────────────────
# Signal performance
# ─────────────────────────────────────────────────────
header("PAPER TRADING PERFORMANCE")

if not signals:
    print("No signals recorded.")
else:
    by_strategy = defaultdict(list)
    for s in signals:
        by_strategy[s.get('strategy', 'max_edge')].append(s)

    for strat, rows in by_strategy.items():
        subheader(f"Strategy: {strat}")
        won = [r for r in rows if r.get('status') == 'won']
        lost = [r for r in rows if r.get('status') == 'lost']
        pending = [r for r in rows if r.get('status') == 'pending']
        settled = won + lost
        total_stake = sum(r.get('stake_usd') or 0 for r in rows)
        settled_stake = sum(r.get('stake_usd') or 0 for r in settled)
        realized = sum(r.get('outcome_pnl') or 0 for r in settled)
        win_rate = len(won) / len(settled) if settled else None
        roi = realized / settled_stake if settled_stake > 0 else None
        expected_pnl = sum((r.get('stake_usd') or 0) * (r.get('ev') or 0) for r in settled)

        print(f"Total:    {len(rows)}")
        print(f"  Won:    {len(won)}")
        print(f"  Lost:   {len(lost)}")
        print(f"  Pending:{len(pending)}")
        if settled:
            print(f"Win rate: {win_rate*100:.1f}%")
        print(f"Total stake: ${total_stake:.2f}")
        print(f"Settled stake: ${settled_stake:.2f}")
        print(f"Realized P&L: ${realized:+.2f}")
        print(f"Expected (EV): ${expected_pnl:+.2f}")
        if roi is not None:
            print(f"ROI: {roi*100:+.1f}%")

        # Win rate by timing
        timing_buckets = defaultdict(lambda: {'won': 0, 'lost': 0, 'pending': 0})
        for r in rows:
            t = r.get('timing') or 'unknown'
            s = r.get('status') or 'pending'
            if s == 'won': timing_buckets[t]['won'] += 1
            elif s == 'lost': timing_buckets[t]['lost'] += 1
            else: timing_buckets[t]['pending'] += 1

        print("\nBy timing:")
        for t, b in timing_buckets.items():
            settled_t = b['won'] + b['lost']
            wr = (b['won'] / settled_t * 100) if settled_t else None
            wr_txt = f"{wr:.0f}%" if wr is not None else "—"
            print(f"  {t:<10}: won={b['won']}, lost={b['lost']}, pending={b['pending']}, win_rate={wr_txt}")

        # Win rate by city
        by_city = defaultdict(lambda: {'won': 0, 'lost': 0, 'pending': 0, 'pnl': 0.0})
        for r in rows:
            c = r.get('city') or '?'
            s = r.get('status') or 'pending'
            if s == 'won':
                by_city[c]['won'] += 1
                by_city[c]['pnl'] += r.get('outcome_pnl') or 0
            elif s == 'lost':
                by_city[c]['lost'] += 1
                by_city[c]['pnl'] += r.get('outcome_pnl') or 0
            else:
                by_city[c]['pending'] += 1

        print("\nBy city:")
        for c, b in by_city.items():
            settled_c = b['won'] + b['lost']
            wr = (b['won'] / settled_c * 100) if settled_c else None
            wr_txt = f"{wr:.0f}%" if wr is not None else "—"
            print(f"  {c:<10}: won={b['won']}, lost={b['lost']}, pending={b['pending']}, pnl=${b['pnl']:+.2f}, wr={wr_txt}")

# ─────────────────────────────────────────────────────
# Market calibration from prices.jsonl
# ─────────────────────────────────────────────────────
header("MARKET CALIBRATION FROM PRICES LOG")

# For each (city, date) with an observation, find:
#   - Did the winning bucket's price rise over time? By how much?
#   - At each timing bucket (early/mid/late), what was the winning bucket's YES price?
if not prices:
    print("No price log.")
else:
    # Group prices by (city, date)
    by_event = defaultdict(list)
    for p in prices:
        key = (p.get('city'), p.get('target_date'))
        by_event[key].append(p)

    calibration_by_timing = defaultdict(list)  # timing -> list of (winning_bucket_yes_price, cnt)

    for (city, date), rows in by_event.items():
        if city not in observations or date not in observations[city]:
            continue
        obs_v = observations[city][date]  # integer METAR max
        # winning bucket is single bucket with bucket_temp == obs_v
        # or below/above if obs_v is at extremes
        # for our purposes just match bucket_temp == obs_v (singles)
        for p in rows:
            if p.get('bucket_type') != 'single':
                continue
            if p.get('bucket_temp') != obs_v:
                continue
            mtc = p.get('minutes_to_close')
            if mtc is None: continue
            if mtc >= 480: timing = 'early'
            elif mtc >= 60: timing = 'mid'
            else: timing = 'late'
            yes_price = p.get('yes_price')
            if yes_price is not None:
                calibration_by_timing[timing].append(yes_price)

    print("Winning bucket's YES price by timing (across all resolved events):")
    print(f"\n{'Timing':<15} {'N snapshots':>12} {'Avg YES price':>15} {'Median':>10}")
    for timing in ['early', 'mid', 'late']:
        vals = calibration_by_timing[timing]
        if vals:
            avg = mean(vals)
            med = median(vals)
            print(f"{timing:<15} {len(vals):>12} {avg*100:>13.1f}% {med*100:>9.1f}%")
        else:
            print(f"{timing:<15} {0:>12} {'—':>13} {'—':>9}")

# ─────────────────────────────────────────────────────
# Day-by-day outcome summary
# ─────────────────────────────────────────────────────
header("DAY-BY-DAY OUTCOMES")
all_dates = set()
for city, dates in observations.items():
    for d in dates:
        all_dates.add(d)

for date in sorted(all_dates):
    for city in observations:
        if date not in observations[city]: continue
        obs_v = observations[city][date]
        # find forecast for this (city, date)
        key = (city, date)
        if key not in latest: continue
        r = latest[key]
        models = r.get('models') or {}
        cons = r.get('consensus')

        per_model_txt = " ".join(
            f"{m[:3]}={v:.1f}" + ('*' if round(v) == obs_v else ' ')
            for m, v in models.items() if v is not None
        )

        cons_txt = f"cons={cons:.2f}" if cons is not None else 'cons=?'
        cons_hit = '*' if cons is not None and round(cons) == obs_v else ' '

        print(f"{date} {city:<10} METAR={obs_v}°C | {per_model_txt} | {cons_txt}{cons_hit}")

print("\n(* = round(value) == METAR — would have won bucket)")

# ─────────────────────────────────────────────────────
# Signal details — settled ones
# ─────────────────────────────────────────────────────
header("SETTLED SIGNALS DETAIL")
settled = [s for s in signals if s.get('status') in ('won', 'lost')]
if not settled:
    print("No settled signals yet.")
else:
    print(f"{'date':<12} {'city':<8} {'strategy':<13} {'bucket':<8} {'our_p':>6} {'mkt':>6} {'edge':>7} {'stake':>7} {'status':<6} {'pnl':>7}")
    for s in sorted(settled, key=lambda r: (r['target_date'], r['city'])):
        print(f"{s['target_date']:<12} {s['city']:<8} {s.get('strategy','?'):<13} "
              f"{s['bucket_label']:<8} {s['our_prob']*100:>5.1f}% "
              f"{s['yes_price']*100:>5.1f}% {s['edge']*100:>+6.1f}% "
              f"${s['stake_usd']:>6.2f} {s['status']:<6} ${s.get('outcome_pnl',0):>+6.2f}")
