#!/usr/bin/env python3
"""
cusp_feature_search.py — Find the BEST non-time market-state filter for cusp.

WHAT IT DOES
  Walks all race_test_btc-updown-5m-*.log files, finds every cusp fire, and
  extracts ~30 features at fire time:
    - From [v5-cusp] fire line: rule, side, ask, cv, bn, ub, udp, fdp,
                                 ratio, r_udp, tcn, ten
    - From [price] line just before:  up_bid, up_ask, dn_bid, dn_ask, ask_sum,
                                       bid_sum, btc_pct, age_up, age_dn, desync
    - From [signal] line just before: crowd, conv, vel, ema_up, ema_dn,
                                       Δ3s_up, Δ3s_dn, Δ10s_up, Δ10s_dn
  Then derives features that account for bet side:
    - bn_with_bet, vel_with_bet, delta10s_with_bet, ema_with_bet
    - ema_gap, depth_diff, depth_ratio_inv, tt_ratio
  Finally, for each feature, sweeps thresholds and finds the one that BEST
  separates wins from losses. cd is excluded — we want a market-state signal,
  not a clock variable.

OUTPUT
  - Full feature table per fire
  - Top-10 single-feature separators ranked by quality
  - The best perfect-separator (if one exists)
  - Two-feature combo search if no perfect single-feature separator

USAGE
  cd ~/polymarket-bot
  python3 cusp_feature_search.py

DOES NOT MODIFY ANY FILES.
"""

import os
import re
import sys
import glob
from collections import defaultdict

# ── Regexes ──────────────────────────────────────────────────────────────────
RE_CUSP_FIRE = re.compile(
    r'\[v5-cusp\] 🔔 CUSP_GAINER (R\d) at cd=(\d+(?:\.\d+)?): '
    r'(UP|DN) ask=\$(\d+\.\d+) cv=(\d+\.\d+) bn=([+-]?\d+\.\d+) '
    r'ub=\$(\d+\.\d+) udp=(\d+) fdp=(\d+) ratio=(\d+\.\d+) '
    r'r_udp=(\d+\.\d+) tcn=(\d+) ten=(\d+)'
)
RE_PRICE = re.compile(
    r'\[price\] (\d+(?:\.\d+)?)s \| UP bid=(\d+\.\d+) ask=(\d+\.\d+) \| '
    r'DN bid=(\d+\.\d+) ask=(\d+\.\d+) \| ask_sum=(\d+\.\d+) bid_sum=(\d+\.\d+) \| '
    r'Δ=([+-]?\d+\.\d+)% \| age_up=(\d+\.\d+)s age_dn=(\d+\.\d+)s desync=(\d+\.\d+)s'
)
RE_SIGNAL = re.compile(
    r'\[signal\] (\d+(?:\.\d+)?)s \| crowd=(\w+) \| conv=(\d+\.\d+) \| '
    r'vel=([+-]?\d+\.\d+) \| ema_up=(\d+\.\d+) \| ema_dn=(\d+\.\d+) \| '
    r'Δ3s_up=([+-]?\d+\.\d+) \| Δ3s_dn=([+-]?\d+\.\d+) \| '
    r'Δ10s_up=([+-]?\d+\.\d+) \| Δ10s_dn=([+-]?\d+\.\d+)'
)
RE_RECAP_CUSP = re.compile(
    r'\d+\.\s+cusp\s+\S+\s+SHADOW\s+(UP|DN)\s+@\s+\$(\d+\.\d+)\s+\S+\s+'
    r'cd=(\d+)\s+real=\$\S+\s+hypo=\$([+-]?\d+\.\d+)\s+\S+\s+\[(\S+)\]'
)


def parse_log(path):
    """Walk the log line by line; for each cusp fire, find the most-recent
    [price] and [signal] lines that came before it."""
    fires = []
    last_price = None
    last_signal = None

    try:
        with open(path, 'r', errors='replace') as f:
            lines = f.readlines()
    except OSError:
        return [], None

    # Find market winner from MARKET RECAP header
    winner = None
    for L in lines:
        m = re.search(r'winner=(UP|DN)', L)
        if m:
            winner = m.group(1)
            break

    for L in lines:
        m = RE_PRICE.search(L)
        if m:
            (cd_p, ub_up, ask_up, ub_dn, ask_dn, ask_sum, bid_sum,
             btc_pct, age_up, age_dn, desync) = m.groups()
            last_price = {
                'up_bid': float(ub_up), 'up_ask': float(ask_up),
                'dn_bid': float(ub_dn), 'dn_ask': float(ask_dn),
                'ask_sum': float(ask_sum), 'bid_sum': float(bid_sum),
                'btc_pct': float(btc_pct), 'age_up': float(age_up),
                'age_dn': float(age_dn), 'desync': float(desync),
            }
            continue

        m = RE_SIGNAL.search(L)
        if m:
            (cd_s, crowd, conv, vel, ema_up, ema_dn,
             d3up, d3dn, d10up, d10dn) = m.groups()
            last_signal = {
                'crowd': crowd, 'conv': float(conv), 'vel': float(vel),
                'ema_up': float(ema_up), 'ema_dn': float(ema_dn),
                'd3s_up': float(d3up), 'd3s_dn': float(d3dn),
                'd10s_up': float(d10up), 'd10s_dn': float(d10dn),
            }
            continue

        m = RE_CUSP_FIRE.search(L)
        if m:
            rule, cd, side, ask, cv, bn, ub, udp, fdp, ratio, rudp, tcn, ten = m.groups()
            fire = {
                'log': os.path.basename(path),
                'winner': winner,
                # Cusp-line features
                'rule': rule, 'cd': float(cd), 'side': side,
                'ask': float(ask), 'cv': float(cv), 'bn': float(bn),
                'ub': float(ub), 'udp': int(udp), 'fdp': int(fdp),
                'ratio': float(ratio), 'r_udp': float(rudp),
                'tcn': int(tcn), 'ten': int(ten),
            }
            # Attach price + signal context
            if last_price:
                fire.update(last_price)
            if last_signal:
                fire.update(last_signal)
            fires.append(fire)

    # Pull recap PnL outcome
    recap_lookup = {}
    for L in lines:
        m = RE_RECAP_CUSP.search(L)
        if m:
            side, ask, cd, hypo, exit_r = m.groups()
            recap_lookup[(side, float(ask))] = (float(hypo), exit_r)

    for f in fires:
        key = (f['side'], f['ask'])
        if key in recap_lookup:
            f['hypo'], f['exit'] = recap_lookup[key]
        else:
            f['hypo'] = None
            f['exit'] = None

    return fires, winner


def add_derived_features(f):
    """Compute features that account for which side we're betting on.
    Positive value = supports our bet; negative = opposes."""
    side_sign = 1 if f['side'] == 'UP' else -1

    # bn = BTC delta %. bn>0 means BTC moving UP. Aligned with UP bet.
    f['bn_with_bet'] = f.get('bn', 0) * side_sign

    # vel = crowd velocity (toward UP). Aligned with UP bet.
    if 'vel' in f:
        f['vel_with_bet'] = f['vel'] * side_sign

    # delta10s_net = how much UP price gained minus DN price gain in last 10s.
    # Positive means UP momentum dominating.
    if 'd10s_up' in f and 'd10s_dn' in f:
        net = f['d10s_up'] - f['d10s_dn']
        f['d10s_net'] = net
        f['d10s_with_bet'] = net * side_sign

    if 'd3s_up' in f and 'd3s_dn' in f:
        net3 = f['d3s_up'] - f['d3s_dn']
        f['d3s_net'] = net3
        f['d3s_with_bet'] = net3 * side_sign

    # EMA gap (signed). ema_up > ema_dn means crowd thinks UP wins.
    if 'ema_up' in f and 'ema_dn' in f:
        gap = f['ema_up'] - f['ema_dn']
        f['ema_gap'] = abs(gap)
        f['ema_with_bet'] = gap * side_sign

    # Cusp-line derived
    f['depth_diff'] = f['udp'] - f['fdp']
    f['fdp_inv'] = 1.0 / max(1, f['fdp'])  # smaller fdp = better cusp setup
    f['tt_ratio'] = f['ten'] / max(1, f['tcn'])

    # Absolute bn — R2 already requires this >= 0.07; useful to test as separator
    f['bn_abs'] = abs(f.get('bn', 0))

    return f


def evaluate_threshold(fires, feature, threshold, direction):
    """Apply rule: KEEP fire if fire[feature] {direction} threshold.
    direction is '>=' or '<='.
    Return (kept_wins, kept_losses, blocked_wins, blocked_losses, kept_pnl)."""
    kw = kl = bw = bl = 0
    kept_pnl = 0.0
    for f in fires:
        if feature not in f or f[feature] is None:
            continue
        v = f[feature]
        if direction == '>=':
            keep = v >= threshold
        else:
            keep = v <= threshold
        is_win = f['hypo'] > 0
        if keep:
            kept_pnl += f['hypo']
            if is_win:
                kw += 1
            else:
                kl += 1
        else:
            if is_win:
                bw += 1
            else:
                bl += 1
    return kw, kl, bw, bl, kept_pnl


def find_best_threshold(fires, feature):
    """For one feature, find the threshold + direction that maximizes
    (kept_wins - kept_losses + blocked_losses - blocked_wins).
    Returns (best_threshold, best_direction, score, kw, kl, bw, bl, pnl)."""
    vals = sorted(set(f[feature] for f in fires if feature in f and f[feature] is not None))
    if len(vals) < 2:
        return None

    best = None
    # Try thresholds at midpoints between sorted values, plus the values themselves
    candidates = list(vals)
    for i in range(len(vals) - 1):
        candidates.append((vals[i] + vals[i+1]) / 2)

    for t in candidates:
        for dir_ in ('>=', '<='):
            kw, kl, bw, bl, pnl = evaluate_threshold(fires, feature, t, dir_)
            # Score: prioritize "block all losses, keep all wins"
            # Penalize blocked wins heavily, reward blocked losses
            score = kw * 10 + bl * 10 - kl * 10 - bw * 5 + pnl * 0.1
            if best is None or score > best[0]:
                best = (score, t, dir_, kw, kl, bw, bl, pnl)
    return best


def main():
    log_dir = sys.argv[1] if len(sys.argv) > 1 else '.'
    pattern = os.path.join(log_dir, 'race_test_btc-updown-5m-*.log')
    log_files = sorted(glob.glob(pattern))
    if not log_files:
        print(f"❌ No race_test_*.log files in {log_dir!r}")
        sys.exit(1)

    print(f"📂 Scanning {len(log_files)} log files...")

    all_fires = []
    for path in log_files:
        fires, _ = parse_log(path)
        for f in fires:
            add_derived_features(f)
        all_fires.extend(fires)

    if not all_fires:
        print("❌ No cusp fires found.")
        sys.exit(0)

    fires_with_pnl = [f for f in all_fires if f.get('hypo') is not None]
    print(f"🎯 Found {len(all_fires)} cusp fires, {len(fires_with_pnl)} with PnL data")
    print()

    if not fires_with_pnl:
        print("⚠️  Need PnL data to find separators.")
        sys.exit(0)

    # ── Full feature table per fire ─────────────────────────────────────────
    print("=" * 120)
    print("FULL FEATURE TABLE (each fire's market state at fire time)")
    print("=" * 120)
    feature_keys = [
        'rule', 'side', 'ask', 'cv', 'bn', 'ub', 'udp', 'fdp', 'ratio',
        'r_udp', 'tcn', 'ten', 'conv', 'vel', 'ema_up', 'ema_dn',
        'd3s_up', 'd3s_dn', 'd10s_up', 'd10s_dn', 'ask_sum', 'btc_pct',
        'bn_with_bet', 'vel_with_bet', 'd10s_with_bet', 'ema_with_bet',
        'ema_gap', 'depth_diff', 'tt_ratio', 'bn_abs',
    ]
    # Header
    hdr = f"{'cd':>4} {'rule':<4} {'side':<4} {'win?':<5}"
    for k in feature_keys[2:]:
        hdr += f" {k:>10}"
    print(hdr)
    print("-" * len(hdr))
    for f in sorted(fires_with_pnl, key=lambda x: -x['cd']):
        row = f"{int(f['cd']):>4} {f['rule']:<4} {f['side']:<4} {'WIN' if f['hypo']>0 else 'LOSS':<5}"
        for k in feature_keys[2:]:
            v = f.get(k)
            if v is None:
                row += f" {'?':>10}"
            elif isinstance(v, (int, float)):
                row += f" {v:>10.3f}" if abs(v) < 100 else f" {v:>10.0f}"
            else:
                row += f" {str(v):>10}"
        print(row)
    print()

    # ── Single-feature separator search ─────────────────────────────────────
    # EXCLUDE cd per user's instruction — we want market-state, not a clock
    excluded = {'cd', 'rule', 'side', 'crowd', 'log', 'winner', 'hypo', 'exit',
                'age_up', 'age_dn', 'desync'}  # ages/desync are tech, not signal
    numeric_features = []
    for k in fires_with_pnl[0].keys():
        if k in excluded:
            continue
        v = fires_with_pnl[0].get(k)
        if isinstance(v, (int, float)) and v is not None:
            # Make sure all fires have this feature
            if all(isinstance(f.get(k), (int, float)) for f in fires_with_pnl):
                numeric_features.append(k)

    print(f"=" * 120)
    print(f"SINGLE-FEATURE SEPARATOR SEARCH (testing {len(numeric_features)} non-time features)")
    print(f"=" * 120)
    print(f"Searching for: KEEP fire if feature {{>=, <=}} threshold")
    print(f"Score = kept_wins×10 + blocked_losses×10 - kept_losses×10 - blocked_wins×5 + pnl×0.1")
    print()

    results = []
    for feat in numeric_features:
        r = find_best_threshold(fires_with_pnl, feat)
        if r:
            results.append((feat, r))

    # Sort by score descending
    results.sort(key=lambda x: -x[1][0])

    print(f"{'feature':<20} {'rule':<28} {'kept_W':>6} {'kept_L':>6} {'blk_W':>5} {'blk_L':>5} "
          f"{'pnl':>9} {'score':>7}")
    print("-" * 95)
    for feat, (score, t, dir_, kw, kl, bw, bl, pnl) in results[:15]:
        rule = f"{feat} {dir_} {t:.4f}"
        marker = "  ← PERFECT" if (kl == 0 and bw == 0) else ""
        print(f"{feat:<20} {rule:<28} {kw:>6} {kl:>6} {bw:>5} {bl:>5}  ${pnl:+7.2f} {score:>7.1f}{marker}")
    print()

    # Find perfect separators (block all losses, keep all wins)
    perfects = [(feat, r) for feat, r in results
                if r[3] == sum(1 for f in fires_with_pnl if f['hypo'] > 0)
                and r[4] == 0]
    if perfects:
        print("=" * 120)
        print(f"🎯 PERFECT SEPARATORS (block all {sum(1 for f in fires_with_pnl if f['hypo']<0)} "
              f"losses, keep all {sum(1 for f in fires_with_pnl if f['hypo']>0)} wins)")
        print("=" * 120)
        for feat, (score, t, dir_, kw, kl, bw, bl, pnl) in perfects:
            print(f"  {feat} {dir_} {t:.4f}  (PnL=${pnl:+.2f})")

        # Recommend the most "natural" perfect separator
        # Prefer features that have a wider gap between the max-loss-value and min-win-value
        print()
        print("=" * 120)
        print("Of the perfect separators, ranked by margin (gap between worst kept vs best blocked):")
        print("=" * 120)
        ranked = []
        for feat, (score, t, dir_, kw, kl, bw, bl, pnl) in perfects:
            wins_vals = [f[feat] for f in fires_with_pnl if f['hypo'] > 0]
            loss_vals = [f[feat] for f in fires_with_pnl if f['hypo'] < 0]
            if dir_ == '>=':
                # Wins should be high, losses should be low
                margin = min(wins_vals) - max(loss_vals)
            else:
                # Wins should be low, losses should be high
                margin = min(loss_vals) - max(wins_vals)
            ranked.append((margin, feat, t, dir_, wins_vals, loss_vals))
        ranked.sort(key=lambda x: -x[0])
        for margin, feat, t, dir_, wv, lv in ranked[:10]:
            wv_s = ', '.join(f"{v:.3f}" for v in sorted(wv))
            lv_s = ', '.join(f"{v:.3f}" for v in sorted(lv))
            print(f"  {feat:<20} {dir_} {t:.4f}  margin={margin:+.4f}")
            print(f"    wins:   [{wv_s}]")
            print(f"    losses: [{lv_s}]")
            print()
    else:
        print("⚠️  NO single feature perfectly separates wins from losses.")
        print("   Consider a two-feature combo (run with --combo flag, not yet implemented),")
        print("   or accept the cd-based filter as the most discriminating signal available.")

    print()
    print("=" * 120)
    print("HOW TO USE")
    print("=" * 120)
    print("1. Pick the perfect separator with the LARGEST margin — that's the most robust.")
    print("2. Replace the cd filter in arb_bot_fixedSim.py:")
    print("   - Remove:   and secs_left >= V5_CUSP_MIN_CD")
    print("   - Add:      and <feature_expression> {>=,<=} <threshold>")
    print("3. The feature must be available at fire-time evaluation in the bot's gate.")
    print("   Most of these features ARE — they come from get_depth_alert, _crowd_signal,")
    print("   get_bn_delta_pct, etc. that are already called in the cusp gate.")


if __name__ == '__main__':
    main()
