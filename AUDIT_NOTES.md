# Audit Notes

## Railway State Boundaries

Git provides the source code, baseline sample data, and baseline `data/real`
CSV/meta files. These files make the lab runnable after checkout, but they are
not the mutable Railway state.

Railway persistent state should live on the mounted volume at `/mnt/data`:

- `REAL_DATA_DIR=/mnt/data/real` stores refreshed SPY/GLD CSV and meta files.
- `SHADOW_STATE_PATH=/mnt/data/shadow_state.json` stores historical and forward
  shadow observation state.

The dashboard refresh button writes normalized market data only to
`REAL_DATA_DIR` and writes shadow records only through `SHADOW_STATE_PATH`. It
does not write raw CSV copies into the repo, place orders, mutate a portfolio,
or run on a schedule.

On redeploy or restart, Git-tracked files are restored from the deployment
image, while `/mnt/data` persists independently if the Railway volume remains
attached. If the volume or env vars are missing, `/admin/refresh` refuses to run
and returns setup guidance.
