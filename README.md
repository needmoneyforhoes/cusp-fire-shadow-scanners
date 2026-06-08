# cusp-fire-shadow-scanners

Two offline scanners that replay race-test logs to validate the cusp (CUSP_GAINER) shadow strategy's countdown filter and search for a non-time replacement.

The cusp gate's proposed live filter `V5_CUSP_MIN_CD = 100` was tuned on ~5 fires. These scripts replay the full `race_test_btc-updown-5m-*.log` history (hundreds of markets) to test the cutoff at scale and to rank single-feature win/loss separators. Read-only; no trades, no writes, no credentials.

## Scripts

| Script | What it does |
| --- | --- |
| `cusp_filter_validate.py` | Parses every cusp fire (rule, side, ask, `bn`, winner, recap `hypo` PnL, exit reason) and sweeps `min_cd` over {0, 50, 75, 90, 100, 110, 120, 150, 180}, reporting kept/blocked W/L, WR, and PnL delta vs baseline. Also prints per-rule WR/PnL, per-rule cd distributions, and a `bn`-direction-agreement check. |
| `cusp_feature_search.py` | Extracts ~30 features per fire from `[v5-cusp]`, `[price]`, and `[signal]` lines, derives side-aware features (`bn_with_bet`, `vel_with_bet`, `d10s_with_bet`, `ema_with_bet`, `ema_gap`, `depth_diff`, `tt_ratio`, `bn_abs`), then sweeps each feature's threshold and direction to rank single-feature separators. `cd` is excluded. Flags any perfect separator and ranks it by margin. |

Both match each fire to its `MARKET RECAP` line by `(side, ask)` within a market to recover `hypo` PnL and exit reason.

## Usage

```bash
# Default: scan the current directory
python3 cusp_filter_validate.py
python3 cusp_feature_search.py

# Or pass the bot's log directory
python3 cusp_filter_validate.py $DATA_DIR
python3 cusp_feature_search.py $DATA_DIR
```

Each prints a report to stdout: per-fire table, per-rule stats, threshold/feature sweeps, and a recommendation. Run where the full log history lives.

## Data

Reads `race_test_btc-updown-5m-*.log` files from `$DATA_DIR` (the private polymarket-data repo). Logs are gitignored, not committed.

## Requirements

Python 3, standard library only (`os`, `re`, `sys`, `glob`, `collections`). No third-party packages.
