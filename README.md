# cusp-fire-shadow-scanners

Cusp-fire shadow analysis from race-test logs: best non-time feature search and minimum-countdown filter validation.

## Why it exists

The `cusp` (CUSP_GAINER) shadow strategy in the Polymarket 5-minute BTC up/down bot fires on R1/R2/R3 rules, but its proposed live gate — `V5_CUSP_MIN_CD = 100` — was tuned on only ~5 fires. These two offline scanners replay the full `race_test_*.log` history (hundreds of markets) to (a) validate the countdown cutoff at scale and (b) hunt for a stronger *market-state* filter than the clock. Both are read-only analysis tools: neither places trades, touches the bot, or modifies any file.

## What's inside

| Script | What it does |
| --- | --- |
| `cusp_filter_validate.py` | Validates the `V5_CUSP_MIN_CD` countdown filter. Parses every cusp fire (rule, side, ask, `bn`, winner, recap `hypo` PnL/exit), then sweeps `min_cd ∈ {0,50,…,180}` reporting kept/blocked W/L, WR, and PnL delta vs baseline. Also breaks down per-rule WR/PnL, cd distributions, and a secondary `bn`-direction-agreement hypothesis. |
| `cusp_feature_search.py` | Searches for the best **non-time** separator. Extracts ~30 features at fire time from the `[v5-cusp]`, `[price]`, and `[signal]` log lines, derives side-aware features (`bn_with_bet`, `vel_with_bet`, `d10s_with_bet`, `ema_with_bet`, `ema_gap`, `depth_diff`, `tt_ratio`, …), then sweeps every feature's threshold/direction to rank single-feature win/loss separators (`cd` excluded by design) and flags any perfect separator with its margin. |

Both derive each fire's outcome by matching the cusp fire line to its MARKET RECAP `hypo=$…`/exit-reason entry within a market, keyed by `(side, ask)`.

## Requirements

- Python 3 (standard library only — `os`, `re`, `sys`, `glob`, `collections`). No third-party packages, no virtualenv needed.
- Input data: `race_test_btc-updown-5m-*.log` files produced by the trading bot's race-test mode. These logs are runtime artifacts (gitignored, not committed); point the scripts at the directory that holds them — typically `~/polymarket-bot/`.
- No wallet, private key, or network access. These scripts never handle funds.

## Usage

```bash
# Default: scan the current directory for race_test_btc-updown-5m-*.log
python3 cusp_filter_validate.py
python3 cusp_feature_search.py

# Or point at the bot's log directory explicitly
python3 cusp_filter_validate.py ~/polymarket-bot/
python3 cusp_feature_search.py ~/polymarket-bot/
```

Each prints a self-contained report to stdout (per-fire table, per-rule stats, threshold/feature sweeps, and a recommendation). Run them where the full log history lives — usually the VPS.

> Private research software. No warranty; trades/handles real funds at your own risk.
