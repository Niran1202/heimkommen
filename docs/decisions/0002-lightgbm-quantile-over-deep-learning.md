# 0002 · LightGBM quantile regression instead of deep learning

**Status:** accepted

## Context
The simulator needs a *distribution* of delay for each leg, not a point estimate: missed connections live in the
tail. Data is tabular (line, station, hour, weekday, position, previous delay), a few million rows, with
high-cardinality categoricals. Training runs on a laptop, and serving runs on a 1–2 GB VM.

## Decision
One LightGBM model per quantile (5 %–98 %), native categorical handling, time-based split. The simulator samples
delays by interpolating the inverse CDF between predicted quantiles. Cancellations use shrunk historical rates.

## Consequences
- Beats per-line-and-station historical quantiles (pinball 1.006 vs. 1.053) and the historical median (1.786),
  with well-calibrated upper quantiles.
- Minutes to train, milliseconds to predict, ~28 MB artifact.
- Quantile crossing is fixed by sorting; tails beyond the 98th percentile are extrapolated.
- Independent quantile models cannot express correlation *between* legs. That is the main source of optimism on
  tight connections (see evaluation), and a sequence model would not fix it without network-state features either.
