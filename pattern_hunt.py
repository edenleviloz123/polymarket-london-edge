"""
Look for actionable patterns in the winners vs losers.
Specifically — what do winning bets have in common?
"""
import json, os, sys, io
from collections import defaultdict, Counter
from statistics import mean, median

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

def load_jsonl(p):
    if not os.path.exists(p): return []
    out=[]
    for line in open(p, encoding='utf-8'):
        line=line.strip()
        if line:
            try: out.append(json.loads(line))
            except: pass
    return out

def load_json(p):
    return json.load(open(p,encoding='utf-8')) if os.path.exists(p) else {}

signals = load_jsonl('docs/signals.jsonl')
forecasts = load_jsonl('docs/forecasts.jsonl')
obs = load_json('docs/observations.json')

settled = [s for s in signals if s.get('status') in ('won','lost')]
won  = [s for s in settled if s['status']=='won']
lost = [s for s in settled if s['status']=='lost']

def header(t): print(f"\n{'='*72}\n{t}\n{'='*72}")
def sub(t): print(f"\n{'-'*55}\n{t}\n{'-'*55}")

# ───────────────────────────────────────
# 1. Which models had highest win-rate when they were the closest to consensus?
# ───────────────────────────────────────
header("1. WHICH MODEL IS MOST OFTEN CLOSEST TO TRUTH?")

# Build (city,date) -> latest forecast lookup
latest_fc = {}
for r in forecasts:
    k = (r.get('city') or 'london', r.get('target_date'))
    if None in k: continue
    if k not in latest_fc or r.get('ts','') > latest_fc[k].get('ts',''):
        latest_fc[k] = r

MODELS = ['MeteoFrance','ICON','GFS','UKMO','ECMWF']

# For each resolved (city,date), find which model was closest
closest_counter = Counter()
total_events = 0
for (city, date), r in latest_fc.items():
    if city not in obs or date not in obs[city]: continue
    obs_v = obs[city][date]
    models_v = (r.get('models') or {})
    distances = []
    for m in MODELS:
        v = models_v.get(m)
        if v is None: continue
        distances.append((abs(v - obs_v), m))
    if not distances: continue
    distances.sort()
    closest = distances[0][1]
    closest_counter[closest] += 1
    total_events += 1

print(f"\nAmong {total_events} resolved events, which model was closest?")
for m in MODELS:
    cnt = closest_counter[m]
    pct = cnt/total_events*100 if total_events else 0
    bar = '█' * int(pct/2)
    print(f"  {m:<13} {cnt:>4} ({pct:>4.0f}%) {bar}")

# ───────────────────────────────────────
# 2. What characterizes winning bets vs losing bets?
# ───────────────────────────────────────
header("2. WINNERS vs LOSERS — WHAT'S DIFFERENT?")

def stats(rows, field):
    vals = [r.get(field) for r in rows if r.get(field) is not None]
    if not vals: return None
    try:
        return (mean(vals), median(vals), min(vals), max(vals))
    except: return None

print(f"\n{'Field':<22} {'Winners avg':>13} {'Losers avg':>13} {'Difference':>13}")
print('-'*65)
for field in ['our_prob','yes_price','edge','kelly','ev','persistence_minutes','minutes_to_close']:
    ws = stats(won, field)
    ls = stats(lost, field)
    if ws and ls:
        diff = ws[0] - ls[0]
        scale = 100 if field in ('our_prob','yes_price','edge','kelly','ev') else 1
        unit = '%' if field in ('our_prob','yes_price','edge','kelly','ev') else 'min'
        print(f"  {field:<20} {ws[0]*scale:>10.1f}{unit:<2} {ls[0]*scale:>10.1f}{unit:<2} {diff*scale:>+10.1f}{unit}")

# ───────────────────────────────────────
# 3. Win-rate per bucket size (single vs below/above)
# ───────────────────────────────────────
header("3. WIN-RATE BY BUCKET TYPE")
bucket_types = defaultdict(lambda: {'won':0, 'lost':0, 'pnl':0})
for s in settled:
    bt = s.get('bucket_type') or '?'
    bucket_types[bt][s['status']] += 1
    bucket_types[bt]['pnl'] += s.get('outcome_pnl') or 0
print(f"\n  {'Bucket type':<12} {'Won':>5} {'Lost':>5} {'WR':>6} {'PnL':>10}")
for bt, d in bucket_types.items():
    n = d['won']+d['lost']
    wr = d['won']/n*100 if n else 0
    print(f"  {bt:<12} {d['won']:>5} {d['lost']:>5} {wr:>5.0f}% ${d['pnl']:>+8.2f}")

# ───────────────────────────────────────
# 4. Win-rate by yes_price band (cheap vs expensive bets)
# ───────────────────────────────────────
header("4. WIN-RATE BY MARKET PRICE BAND")
price_bands = [
    ("very cheap <5%",      0.00, 0.05),
    ("cheap 5-15%",         0.05, 0.15),
    ("moderate 15-30%",     0.15, 0.30),
    ("expensive 30-60%",    0.30, 0.60),
    ("very expensive >60%", 0.60, 1.01),
]
print(f"\n  {'Price band':<25} {'N':>5} {'Won':>5} {'Lost':>5} {'WR':>6} {'PnL':>10} {'ROI':>8}")
for label, lo, hi in price_bands:
    rows = [s for s in settled if lo <= s.get('yes_price',0) < hi]
    won_r = [r for r in rows if r['status']=='won']
    lost_r = [r for r in rows if r['status']=='lost']
    n = len(rows)
    pnl = sum(r.get('outcome_pnl') or 0 for r in rows)
    stake = sum(r.get('stake_usd') or 0 for r in rows)
    wr = len(won_r)/n*100 if n else 0
    roi = pnl/stake*100 if stake>0 else 0
    print(f"  {label:<25} {n:>5} {len(won_r):>5} {len(lost_r):>5} {wr:>5.0f}% ${pnl:>+8.2f} {roi:>+6.0f}%")

# ───────────────────────────────────────
# 5. Win-rate by our_prob band
# ───────────────────────────────────────
header("5. WIN-RATE BY OUR PROBABILITY BAND")
prob_bands = [
    ("30-40%", 0.30, 0.40),
    ("40-55%", 0.40, 0.55),
    ("55-75%", 0.55, 0.75),
    (">75%",   0.75, 1.01),
]
print(f"\n  {'Our prob':<10} {'N':>5} {'Won':>5} {'Lost':>5} {'Actual WR':>10} {'ROI':>8}")
for label, lo, hi in prob_bands:
    rows = [s for s in settled if lo <= s.get('our_prob',0) < hi]
    won_r = [r for r in rows if r['status']=='won']
    n = len(rows)
    pnl = sum(r.get('outcome_pnl') or 0 for r in rows)
    stake = sum(r.get('stake_usd') or 0 for r in rows)
    wr = len(won_r)/n*100 if n else 0
    roi = pnl/stake*100 if stake>0 else 0
    expected_wr = (lo+hi)/2*100
    print(f"  {label:<10} {n:>5} {len(won_r):>5} {n-len(won_r):>5} {wr:>9.0f}% {roi:>+7.0f}% (expected ~{expected_wr:.0f}%)")

# ───────────────────────────────────────
# 6. Which (city, bucket-temp) wins most often?
# ───────────────────────────────────────
header("6. PATTERNS BY CITY × TEMPERATURE")
city_temp = defaultdict(lambda: {'won':0, 'lost':0, 'pnl':0})
for s in settled:
    key = (s.get('city'), s.get('bucket_temp'))
    city_temp[key][s['status']] += 1
    city_temp[key]['pnl'] += s.get('outcome_pnl') or 0

print(f"\n  {'City':<10} {'Bucket':<8} {'Won':>5} {'Lost':>5} {'WR':>6} {'PnL':>10}")
rows_sorted = sorted(city_temp.items(), key=lambda x: -x[1]['pnl'])
for (city, temp), d in rows_sorted[:10]:
    if not city: continue
    n = d['won']+d['lost']
    if n < 2: continue   # skip noise
    wr = d['won']/n*100
    print(f"  {city:<10} {str(temp)+'°C':<8} {d['won']:>5} {d['lost']:>5} {wr:>5.0f}% ${d['pnl']:>+8.2f}")
print("\n  Bottom 10 (most losing):")
for (city, temp), d in sorted(city_temp.items(), key=lambda x: x[1]['pnl'])[:10]:
    if not city: continue
    n = d['won']+d['lost']
    if n < 2: continue
    wr = d['won']/n*100
    print(f"  {city:<10} {str(temp)+'°C':<8} {d['won']:>5} {d['lost']:>5} {wr:>5.0f}% ${d['pnl']:>+8.2f}")

# ───────────────────────────────────────
# 7. Look at biggest wins and biggest losses individually
# ───────────────────────────────────────
header("7. BIGGEST WINS AND LOSSES")
sub("Top 8 biggest wins")
big_wins = sorted(won, key=lambda r: -(r.get('outcome_pnl') or 0))[:8]
print(f"\n  {'Date':<12} {'City':<8} {'Bucket':<7} {'Strategy':<13} {'Our%':>5} {'Mkt%':>5} {'Stake':>7} {'PnL':>8}")
for s in big_wins:
    print(f"  {s['target_date']:<12} {s['city']:<8} {s['bucket_label'][:6]:<7} {s.get('strategy','?'):<13} "
          f"{s['our_prob']*100:>4.0f}% {s['yes_price']*100:>4.0f}% ${s['stake_usd']:>5.2f} ${s.get('outcome_pnl',0):>+6.2f}")

sub("Top 8 biggest losses")
big_losses = sorted(lost, key=lambda r: (r.get('outcome_pnl') or 0))[:8]
print(f"\n  {'Date':<12} {'City':<8} {'Bucket':<7} {'Strategy':<13} {'Our%':>5} {'Mkt%':>5} {'Stake':>7} {'PnL':>8}")
for s in big_losses:
    print(f"  {s['target_date']:<12} {s['city']:<8} {s['bucket_label'][:6]:<7} {s.get('strategy','?'):<13} "
          f"{s['our_prob']*100:>4.0f}% {s['yes_price']*100:>4.0f}% ${s['stake_usd']:>5.2f} ${s.get('outcome_pnl',0):>+6.2f}")

# ───────────────────────────────────────
# 8. Distance: how far off was the bucket bet vs reality?
# ───────────────────────────────────────
header("8. WHEN WE LOSE — BY HOW MUCH WE MISSED?")
miss_distances = defaultdict(lambda: {'count':0, 'stake':0, 'pnl':0})
for s in lost:
    city = s.get('city')
    date = s.get('target_date')
    bt = s.get('bucket_temp')
    if city not in obs or date not in obs[city]: continue
    actual = obs[city][date]
    if bt is None: continue
    miss = bt - actual   # positive = we bet warmer than reality
    miss_distances[miss]['count'] += 1
    miss_distances[miss]['stake'] += s.get('stake_usd') or 0
    miss_distances[miss]['pnl'] += s.get('outcome_pnl') or 0

print(f"\nDistribution of our miss when we lose (positive = we bet warmer than reality):")
print(f"  {'Miss (°C)':<10} {'Count':>6} {'Stake':>9}")
for miss in sorted(miss_distances.keys()):
    d = miss_distances[miss]
    print(f"  {miss:>+6}    {d['count']:>6} ${d['stake']:>7.2f}")

# Same for wins — were we exactly right?
print(f"\nDistribution of our 'hit' when we win:")
win_distances = defaultdict(lambda: {'count':0, 'pnl':0})
for s in won:
    city = s.get('city')
    date = s.get('target_date')
    bt = s.get('bucket_temp')
    if city not in obs or date not in obs[city]: continue
    actual = obs[city][date]
    if bt is None: continue
    # For single bucket: winning means bt == actual
    # For below: winning means actual <= bt
    # For above: winning means actual >= bt
    btype = s.get('bucket_type')
    if btype == 'single':
        # Always 0 if won
        pass
    else:
        # Could be off by some amount
        pass
