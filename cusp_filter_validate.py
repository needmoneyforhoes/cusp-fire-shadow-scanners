#!/usr/bin/env python3
"""
cusp_filter_validate.py — Validate the proposed V5_CUSP_MIN_CD filter against
your full race_test_*.log history.

WHAT IT DOES
  Walks all race_test_btc-updown-5m-*.log files in the current directory, finds
  every cusp fire (R1, R2, R3) along with its cd, side, ask, bn_delta, rule,
  and the eventual market winner. Then sweeps cd-threshold values and reports
  the WR / PnL impact of each.

WHY YOU NEED IT
  The proposed filter (V5_CUSP_MIN_CD = 100 in arb_bot_fixedSim.py) was derived
  from N=5 cusp fires in market_recap_history.jsonl. That's too small to be
  confident. Your race_test logs typically cover hundreds of markets and will
  contain many more cusp fires we can use to validate.

USAGE
  cd ~/polymarket-bot
  python3 cusp_filter_validate.py
  # Or specify a directory:
  python3 cusp_filter_validate.py /path/to/logs/

OUTPUT
  - Per-fire breakdown (cd, rule, side, $entry, bn, winner, outcome)
  - Per-rule statistics (R1/R2/R3 win rate, PnL)
  - Sweep of cd-threshold filters with W/L/PnL deltas
  - Recommendation if a clear cutoff exists

DOES NOT MODIFY ANY FILES.
"""

import os
import re
import sys
import glob
from collections import defaultdict, Counter

# ── Regexes for the race_test log format ───────────────────────────────────
RE_CUSP_FIRE = re.compile(
    r'\[v5-cusp\] 🔔 CUSP_GAINER (R\d) at cd=(\d+(?:\.\d+)?): '
    r'(UP|DN) ask=\$(\d+\.\d+) cv=(\d+\.\d+) bn=([+-]?\d+\.\d+) '
    r'ub=\$(\d+\.\d+) udp=(\d+) fdp=(\d+) ratio=(\d+\.\d+) '
    r'r_udp=(\d+\.\d+) tcn=(\d+) ten=(\d+)'
)
RE_WINNER = re.compile(r'winner=(UP|DN)')
RE_TP = re.compile(r'\[v5-cusp\].*TP.*\$([+-]?\d+\.\d+)')
RE_SL = re.compile(r'\[v5-cusp\].*SL.*\$([+-]?\d+\.\d+)')
RE_RECAP_CUSP = re.compile(
    r'\d+\.\s*cusp\s+\S+\s+(\S+)\s+\S+\s+@\s+\$(\d+\.\d+)\s+\S+\s+cd=(\d+)\s+'
    r'\S+=\S+\s+hypo=\$([+-]\d+\.\d+)'
)


def parse_log(path):
    """Return list of cusp fires found in this log: dicts with full features + outcome."""
    fires = []
    winner = None
    try:
        with open(path, 'r', errors='replace') as f:
            text = f.read()
    except OSError:
        return []

    # Find market winner — appears in MARKET RECAP header
    m = RE_WINNER.search(text)
    if m:
        winner = m.group(1)

    # All cusp fires in this market
    for m in RE_CUSP_FIRE.finditer(text):
        rule, cd, side, ask, cv, bn, ub, udp, fdp, ratio, rudp, tcn, ten = m.groups()
        fires.append({
            'log': os.path.basename(path),
            'rule': rule,
            'cd': float(cd),
            'side': side,
            'ask': float(ask),
            'cv': float(cv),
            'bn': float(bn),
            'ub': float(ub),
            'udp': int(udp),
            'fdp': int(fdp),
            'ratio': float(ratio),
            'r_udp': float(rudp),
            'tcn': int(tcn),
            'ten': int(ten),
            'winner': winner,
        })

    # Pull the recap line for each fire (gives us hypo_pnl and exit_reason)
    # The recap line format:
    #   N. cusp           🔵 SHADOW DN @ $0.200 5sh cd=73   real=$0.00  hypo=$-0.55 ❌ [SL]
    # NOTE: recap cd often differs from fire-log cd by 1-2s (recorded at tick time
    # vs fire time). Match by (side, ask) within a market — typically unique since
    # cusp_fired flag prevents same-side re-fires.
    re_recap = re.compile(
        r'\d+\.\s+cusp\s+\S+\s+SHADOW\s+(UP|DN)\s+@\s+\$(\d+\.\d+)\s+\S+\s+'
        r'cd=(\d+)\s+real=\$\S+\s+hypo=\$([+-]?\d+\.\d+)\s+\S+\s+\[(\S+)\]'
    )
    recap_lookup = {}  # (side, ask) -> (cd, hypo, exit)
    for m in re_recap.finditer(text):
        side, ask, cd, hypo, exit_r = m.groups()
        recap_lookup[(side, float(ask))] = (int(cd), float(hypo), exit_r)

    # Match each fire to its recap entry (cd-tolerant)
    for f in fires:
        key = (f['side'], f['ask'])
        if key in recap_lookup:
            _cd, f['hypo'], f['exit'] = recap_lookup[key]
        else:
            f['hypo'] = None
            f['exit'] = None

    return fires


def main():
    log_dir = sys.argv[1] if len(sys.argv) > 1 else '.'
    pattern = os.path.join(log_dir, 'race_test_btc-updown-5m-*.log')
    log_files = sorted(glob.glob(pattern))
    if not log_files:
        print(f"❌ No race_test_btc-updown-5m-*.log files in {log_dir!r}")
        print(f"   Try: python3 {sys.argv[0]} ~/polymarket-bot")
        sys.exit(1)

    print(f"📂 Scanning {len(log_files)} log files in {log_dir!r}...")

    all_fires = []
    for path in log_files:
        all_fires.extend(parse_log(path))

    if not all_fires:
        print("❌ No cusp fires found in any log file.")
        sys.exit(0)

    print(f"🎯 Found {len(all_fires)} cusp fire(s) across logs")
    print()

    # Per-fire breakdown
    print("=" * 100)
    print(f"{'cd':<5} {'rule':<4} {'side':<4} {'$entry':<7} {'bn':<8} {'winner':<7} "
          f"{'outcome':<10} {'exit':<7}  log")
    print("-" * 100)
    for f in sorted(all_fires, key=lambda x: -x['cd']):
        # If we have hypo, use it; otherwise infer from side==winner
        if f['hypo'] is not None:
            outcome = '✅ +pnl' if f['hypo'] > 0 else ('❌ -pnl' if f['hypo'] < 0 else '➖ flat')
            outcome_val = f['hypo']
            outstr = f"{outcome} ${outcome_val:+.2f}"
        else:
            outcome = '?'
            outstr = '?'
        ex = f['exit'] or '?'
        print(f"{int(f['cd']):<5} {f['rule']:<4} {f['side']:<4} ${f['ask']:<5.3f}  "
              f"{f['bn']:+.4f}  {f['winner'] or '?':<7} {outstr:<10} [{ex}]  {f['log']}")
    print()

    # Per-rule stats
    print("=" * 100)
    print("Per-rule statistics:")
    by_rule = defaultdict(list)
    for f in all_fires:
        by_rule[f['rule']].append(f)
    for rule in sorted(by_rule):
        fires = by_rule[rule]
        with_pnl = [f for f in fires if f['hypo'] is not None]
        if with_pnl:
            wins = sum(1 for f in with_pnl if f['hypo'] > 0)
            losses = sum(1 for f in with_pnl if f['hypo'] < 0)
            pnl = sum(f['hypo'] for f in with_pnl)
            wr = wins / max(1, wins + losses) * 100
            print(f"  {rule}: {len(fires)} fires, {wins}W/{losses}L (WR={wr:.0f}%), hypo=${pnl:+.2f}")
        else:
            print(f"  {rule}: {len(fires)} fires (no PnL data)")
    print()

    # Filter sweep
    fires_with_pnl = [f for f in all_fires if f['hypo'] is not None]
    if not fires_with_pnl:
        print("⚠️  No fires have PnL data — can't run filter sweep.")
        sys.exit(0)

    print("=" * 100)
    print(f"Filter sweep — V5_CUSP_MIN_CD threshold (n={len(fires_with_pnl)} fires with PnL):")
    print()
    print(f"{'min_cd':<8} {'kept':<7} {'blocked':<8} {'wins':<6} {'losses':<8} {'WR':<6} "
          f"{'kept_pnl':<10} {'blocked_pnl':<12} {'delta_vs_baseline':<18}")
    print("-" * 95)
    baseline_pnl = sum(f['hypo'] for f in fires_with_pnl)
    for thresh in [0, 50, 75, 90, 100, 110, 120, 150, 180]:
        kept = [f for f in fires_with_pnl if f['cd'] >= thresh]
        blocked = [f for f in fires_with_pnl if f['cd'] < thresh]
        wins = sum(1 for f in kept if f['hypo'] > 0)
        losses = sum(1 for f in kept if f['hypo'] < 0)
        wr = wins / max(1, wins + losses) * 100
        kept_pnl = sum(f['hypo'] for f in kept)
        blocked_pnl = sum(f['hypo'] for f in blocked)
        delta = kept_pnl - baseline_pnl
        marker = " ← current proposal" if thresh == 100 else ""
        print(f"  {thresh:<6} {len(kept):<7} {len(blocked):<8} {wins:<6} {losses:<8} "
              f"{wr:>4.0f}%  ${kept_pnl:+8.2f}  ${blocked_pnl:+8.2f}    "
              f"${delta:+.2f}{marker}")
    print()

    # Per-rule cd distribution
    print("=" * 100)
    print("cd distribution by rule (helps see if any rule is fine at all cd):")
    for rule in sorted(by_rule):
        cds = sorted(int(f['cd']) for f in by_rule[rule] if f['hypo'] is not None)
        wins_cds = sorted(int(f['cd']) for f in by_rule[rule]
                          if f['hypo'] is not None and f['hypo'] > 0)
        loss_cds = sorted(int(f['cd']) for f in by_rule[rule]
                          if f['hypo'] is not None and f['hypo'] < 0)
        print(f"  {rule}:")
        print(f"    all cds:    {cds}")
        print(f"    win cds:    {wins_cds}")
        print(f"    loss cds:   {loss_cds}")
    print()

    # bn-direction agreement check (from cd=74 case study)
    print("=" * 100)
    print("Secondary hypothesis: bn-direction agreement")
    print("(Buying DN should require bn < 0; buying UP should require bn > 0)")
    agree = []
    disagree = []
    for f in fires_with_pnl:
        # bn>0 means BTC moving UP. Bet UP is aligned, bet DN is opposed.
        aligned = (f['bn'] > 0 and f['side'] == 'UP') or (f['bn'] < 0 and f['side'] == 'DN')
        if aligned:
            agree.append(f)
        else:
            disagree.append(f)
    if agree:
        a_wins = sum(1 for f in agree if f['hypo'] > 0)
        a_pnl = sum(f['hypo'] for f in agree)
        print(f"  bn AGREES with bet:    {len(agree)} fires, {a_wins}W/{len(agree)-a_wins}L, hypo=${a_pnl:+.2f}")
    if disagree:
        d_wins = sum(1 for f in disagree if f['hypo'] > 0)
        d_pnl = sum(f['hypo'] for f in disagree)
        print(f"  bn DISAGREES with bet: {len(disagree)} fires, {d_wins}W/{len(disagree)-d_wins}L, hypo=${d_pnl:+.2f}")
    print()

    print("=" * 100)
    print("RECOMMENDATIONS")
    print("=" * 100)
    print("Run this script on your VPS where you have your full ~/polymarket-bot/ history.")
    print("Look for the threshold that maximises kept_pnl (or minimises losses while keeping wins).")
    print("If the secondary hypothesis (bn-agreement) shows a clean split, that's a stronger filter.")
    print("Adjust V5_CUSP_MIN_CD in arb_bot_fixedSim.py to match what your data supports.")


if __name__ == '__main__':
    main()
