"""
Three-phase analysis: Pre-Stage-1 / Stage-1-only / Post-Stage-2.
Tells us whether each filter improvement actually moved the needle.
"""
import json, os, sys, io
from collections import defaultdict
from statistics import mean, median

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

STAGE1 = "2026-05-03T12:00:00"
STAGE2 = "2026-05-12T10:00:00"

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

forecasts = load_jsonl('docs/forecasts.jsonl')
signals   = load_jsonl('docs/signals.jsonl')
prices    = load_jsonl('docs/prices.jsonl')
obs       = load_json('docs/observations.json')

def header(t): print(f"\n{'='*72}\n{t}\n{'='*72}")
def sub(t):    print(f"\n{'-'*55}\n{t}\n{'-'*55}")

def aggregate(rows):
    won = [r for r in rows if r.get('status')=='won']
    lost = [r for r in rows if r.get('status')=='lost']
    pending = [r for r in rows if r.get('status')=='pending']
    settled = won+lost
    pnl = sum(r.get('outcome_pnl') or 0 for r in settled)
    stake = sum(r.get('stake_usd') or 0 for r in settled)
    return dict(N=len(rows), won=len(won), lost=len(lost), pending=len(pending),
                wr=len(won)/len(settled) if settled else None,
                pnl=pnl, roi=pnl/stake if stake>0 else None,
                stake=stake)

phase1 = [s for s in signals if (s.get('ts') or '') < STAGE1]
phase2 = [s for s in signals if STAGE1 <= (s.get('ts') or '') < STAGE2]
phase3 = [s for s in signals if (s.get('ts') or '') >= STAGE2]

header("THREE-PHASE OVERVIEW")
print(f"\n{'Phase':<28} {'N':>5} {'Won':>5} {'Lost':>5} {'Pend':>5} {'WinR':>7} {'PnL':>10} {'ROI':>8}")
print('-'*78)
for label, rows in [('Phase 1: pre-Stage-1', phase1),
                    ('Phase 2: Stage 1 only', phase2),
                    ('Phase 3: Stage 1+2', phase3),
                    ('All time', signals)]:
    a = aggregate(rows)
    wr = f"{a['wr']*100:.0f}%" if a['wr'] is not None else '—'
    roi = f"{a['roi']*100:+.1f}%" if a['roi'] is not None else '—'
    print(f"{label:<28} {a['N']:>5} {a['won']:>5} {a['lost']:>5} {a['pending']:>5} "
          f"{wr:>7} ${a['pnl']:>+8.2f} {roi:>8}")

header("BY STRATEGY (Phase 3 only)")
by_strat = defaultdict(list)
for s in phase3:
    by_strat[s.get('strategy','max_edge')].append(s)
for strat, rows in by_strat.items():
    a = aggregate(rows)
    wr = f"{a['wr']*100:.0f}%" if a['wr'] is not None else '—'
    roi = f"{a['roi']*100:+.1f}%" if a['roi'] is not None else '—'
    print(f"  {strat:<14} N={a['N']:<3} won={a['won']:<3} lost={a['lost']:<3} "
          f"pend={a['pending']:<3} winR={wr} PnL=${a['pnl']:+.2f} ROI={roi}")

header("BY TIME-OF-DAY (Phase 3 — did Stage 2 help noon?)")
tod_buckets = defaultdict(list)
for s in phase3:
    tod = s.get('time_of_day')
    if tod: tod_buckets[tod].append(s)
print(f"\n  {'Time':<11} {'N':>3} {'Won':>4} {'Lost':>5} {'WinR':>6} {'PnL':>10} {'ROI':>9}")
for tod in ['night','morning','noon','afternoon','evening']:
    rows = tod_buckets[tod]
    if not rows: continue
    a = aggregate(rows)
    wr = f"{a['wr']*100:.0f}%" if a['wr'] is not None else '—'
    roi = f"{a['roi']*100:+.1f}%" if a['roi'] is not None else '—'
    print(f"  {tod:<11} {a['N']:>3} {a['won']:>4} {a['lost']:>5} {wr:>6} "
          f"${a['pnl']:>+8.2f} {roi:>9}")

sub("Compare to Stage-1-only (Phase 2)")
tod2 = defaultdict(list)
for s in phase2:
    if s.get('time_of_day'): tod2[s['time_of_day']].append(s)
for tod in ['night','morning','noon','afternoon','evening']:
    if tod not in tod2 and tod not in tod_buckets: continue
    p2 = aggregate(tod2[tod]) if tod in tod2 else None
    p3 = aggregate(tod_buckets[tod]) if tod in tod_buckets else None
    p2_str = f"WR={p2['wr']*100:.0f}% ROI={p2['roi']*100:+.0f}% (N={p2['N']})" if p2 and p2['wr'] is not None else 'no data'
    p3_str = f"WR={p3['wr']*100:.0f}% ROI={p3['roi']*100:+.0f}% (N={p3['N']})" if p3 and p3['wr'] is not None else 'no data'
    print(f"  {tod:<11}  Stage1: {p2_str:<30}  Stage1+2: {p3_str}")

header("BY TIMING (early/mid/late) — does persistence change late-vs-early?")
print(f"\n  {'Period':<12} {'Timing':<8} {'N':>3} {'WinR':>6} {'ROI':>8}")
for label, rows in [('Stage 1', phase2), ('Stage 1+2', phase3)]:
    for t in ['early','mid','late']:
        sub_rows = [s for s in rows if s.get('timing')==t]
        if not sub_rows: continue
        a = aggregate(sub_rows)
        wr = f"{a['wr']*100:.0f}%" if a['wr'] is not None else '—'
        roi = f"{a['roi']*100:+.1f}%" if a['roi'] is not None else '—'
        print(f"  {label:<12} {t:<8} {a['N']:>3} {wr:>6} {roi:>8}")

# Persistence analysis: do longer-persisted signals win more?
header("PERSISTENCE → WIN RATE (Phase 3 only)")
p_signals = [s for s in phase3 if s.get('persistence_minutes') is not None]
if p_signals:
    buckets = {'<10min':[], '10-30min':[], '30-90min':[], '>90min':[]}
    for s in p_signals:
        p = s['persistence_minutes']
        if p < 10: buckets['<10min'].append(s)
        elif p < 30: buckets['10-30min'].append(s)
        elif p < 90: buckets['30-90min'].append(s)
        else: buckets['>90min'].append(s)
    print(f"\n  {'Persisted':<12} {'N':>3} {'WinR':>6} {'PnL':>9} {'ROI':>8}")
    for label, rows in buckets.items():
        if not rows: continue
        a = aggregate(rows)
        wr = f"{a['wr']*100:.0f}%" if a['wr'] is not None else '—'
        roi = f"{a['roi']*100:+.1f}%" if a['roi'] is not None else '—'
        print(f"  {label:<12} {a['N']:>3} {wr:>6} ${a['pnl']:>+7.2f} {roi:>8}")
else:
    print("No persistence_minutes data in Phase 3 signals yet.")

# Model accuracy now (all-time, post-bias correction)
header("MODEL ACCURACY (Phase 3 only — post bias correction)")

# Build latest forecast per (city, date) within phase3 window
latest = {}
for r in forecasts:
    k = (r.get('city') or 'london', r.get('target_date'))
    if None in k: continue
    if k[0] not in obs or k[1] not in obs[k[0]]: continue
    ts = r.get('ts','')
    if ts < STAGE2: continue
    if k not in latest or ts > latest[k].get('ts',''):
        latest[k] = r

MODELS = ['MeteoFrance','ICON','GFS','UKMO','ECMWF']

print(f"\nResolved (city, date) in Phase 3 window: {len(latest)}")
err = {m:[] for m in MODELS}
hit = {m:[] for m in MODELS}
cone = []; conh = []
for (city, date), r in latest.items():
    ov = obs[city][date]
    for m,v in (r.get('models') or {}).items():
        if v is None or m not in MODELS: continue
        err[m].append(v-ov)
        hit[m].append(round(v)==ov)
    cm = r.get('consensus')
    if cm is not None:
        cone.append(cm-ov)
        conh.append(round(cm)==ov)

print(f"\n  {'Model':<14} {'MAE':>6} {'Bias':>7} {'BucketHit':>11} {'N':>4}")
for m in MODELS:
    if err[m]:
        mae = mean(abs(e) for e in err[m]); bi = mean(err[m])
        bh = mean(hit[m])*100; n = len(err[m])
        print(f"  {m:<14} {mae:>5.2f}° {bi:>+6.2f}° {bh:>10.0f}% {n:>4}")
if cone:
    print(f"  {'Consensus':<14} {mean(abs(e) for e in cone):>5.2f}° "
          f"{mean(cone):>+6.2f}° {mean(conh)*100:>10.0f}% {len(cone):>4}")

# Per city
print()
for city in ['london', 'paris']:
    err_c = {m:[] for m in MODELS}
    hit_c = {m:[] for m in MODELS}
    cone_c = []; conh_c = []
    for (c, date), r in latest.items():
        if c != city: continue
        ov = obs[c][date]
        for m,v in (r.get('models') or {}).items():
            if v is None or m not in MODELS: continue
            err_c[m].append(v-ov)
            hit_c[m].append(round(v)==ov)
        cm = r.get('consensus')
        if cm is not None:
            cone_c.append(cm-ov)
            conh_c.append(round(cm)==ov)
    print(f"\n  === {city.upper()} ===")
    print(f"  {'Model':<14} {'MAE':>6} {'Bias':>7} {'BucketHit':>11} {'N':>4}")
    for m in MODELS:
        if err_c[m]:
            mae = mean(abs(e) for e in err_c[m]); bi = mean(err_c[m])
            bh = mean(hit_c[m])*100; n = len(err_c[m])
            print(f"  {m:<14} {mae:>5.2f}° {bi:>+6.2f}° {bh:>10.0f}% {n:>4}")
    if cone_c:
        print(f"  {'Consensus':<14} {mean(abs(e) for e in cone_c):>5.2f}° "
              f"{mean(cone_c):>+6.2f}° {mean(conh_c)*100:>10.0f}% {len(cone_c):>4}")

# Market vs us, phase 3
header("MARKET vs US — Phase 3")

last_snap = {}
for p in prices:
    k = (p.get('city'), p.get('target_date'))
    if not all(k): continue
    mtc = p.get('minutes_to_close')
    if mtc is None: continue
    if k not in last_snap or mtc < last_snap[k]['_mtc']:
        last_snap[k] = {'_mtc': mtc, '_buckets': {}}
    if mtc == last_snap[k]['_mtc']:
        last_snap[k]['_buckets'][p.get('bucket_label')] = {
            'price': p.get('yes_price') or 0,
            'temp': p.get('bucket_temp'),
            'type': p.get('bucket_type'),
        }

def bucket_match(btype, btemp, ov):
    if btype=='single': return btemp==ov
    if btype=='below':  return ov<=btemp
    if btype=='above':  return ov>=btemp
    return False

us=0; mkt=0; both=0; only_us=0; only_mkt=0; both_wrong=0; total=0
for (city, date), r in latest.items():
    if (city,date) not in last_snap: continue
    ov = obs[city][date]
    our = round(r['consensus']) if r.get('consensus') is not None else None
    bs = last_snap[(city,date)]['_buckets']
    if not bs: continue
    top = max(bs.items(), key=lambda kv: kv[1]['price'])
    mkt_hit = bucket_match(top[1]['type'], top[1]['temp'], ov)
    our_hit = (our == ov)
    total += 1
    if our_hit: us += 1
    if mkt_hit: mkt += 1
    if our_hit and mkt_hit: both += 1
    elif our_hit: only_us += 1
    elif mkt_hit: only_mkt += 1
    else: both_wrong += 1

if total:
    print(f"\nPhase 3 ({total} events): us {us}/{total} ({us/total*100:.0f}%) | "
          f"market {mkt}/{total} ({mkt/total*100:.0f}%)")
    print(f"  Both correct: {both}, only us: {only_us}, only market: {only_mkt}, both wrong: {both_wrong}")
