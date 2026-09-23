# Evaluation

Two questions: *is the delay model good?* and *are the journey probabilities right?* Both are answered on data
the model never saw. Everything is split **by time**, never randomly.

## 1. Delay model (per stop event)

`ml/pipelines/train.py`, model `v1`.

| | |
|---|---|
| Training months | 2026-03 to 2026-06 (2.71M arrival/departure events, sampled) |
| Test months | 2026-07, 2026-08 (579k events) |
| Model | LightGBM, one model per quantile (5, 10, 25, 50, 75, 90, 95, 98 %) |
| Features | product, operator, line, station, hour, weekday, stop number and position along the run, arrival/departure, delay at the previous stop (masked for half the training rows) |

Mean quantile (pinball) loss on the test months, lower is better:

| Method | Loss |
|---|---|
| **LightGBM, planning mode** (previous delay unknown) | **1.006** |
| LightGBM, live mode (previous delay known) | 0.986 |
| Historical quantiles per line × station × arrival/departure | 1.053 |
| Historical median ("use the historical median") | 1.786 |

Calibration of the upper quantiles, which drive missed connections: 88.5 % of delays fell below the predicted
90th percentile, 93.9 % below the 95th, 97.3 % below the 98th. Lower quantiles look over-covered (the 5th
percentile is "covered" 31 % of the time) because delays are whole minutes with a large point mass at 0–1 min.
That is a property of the data, not a calibration failure.

Cancellations use historical rates per line × station, shrunk towards the line and product rate. Brier score
0.0338 vs. 0.0343 for a single global rate: **only a marginal improvement**. Cancellations are hard to predict
from history alone.

## 2. Journeys: historical replay

`ml/pipelines/evaluate_replay.py`. For every second day of July and August 2026, 12 origin/destination pairs
that matter for the region (Stuttgart, Freiburg, Konstanz, Karlsruhe, Tübingen, Offenburg, Singen towards
Villingen, Donaueschingen, Rottweil, Tuttlingen, St. Georgen, Triberg) and four departure times (17:30, 19:30,
21:00, 22:00), we:

1. plan the next journey with RAPTOR on the GTFS timetable of that day (Deutschlandticket only);
2. predict with three methods;
3. look up what really happened: actual departure and arrival of every train at the boarding and alighting
   station, cancellations. A connection *worked* if `actual arrival + change time ≤ actual departure` of the
   next train. *Stranded* means a connection failed and the timetable had no way on from there that night.

891 of 910 planned journeys had complete actual data (19 had a train missing from the delay data).

| Brier score, lower is better | Observed rate | Timetable only | Historical median | **Simulator** |
|---|---|---|---|---|
| All connections work | 75.9 % | 0.241 | 0.168 | **0.127** |
| Arrive ≤ 5 min late | 52.7 % | 0.473 | 0.391 | **0.216** |
| Stranded | 4.3 % | 0.043 | 0.043 | **0.033** |

*Timetable only* says 100 % / 100 % / 0 %. *Historical median* adds each train's historical median delay and
says yes or no. The simulator samples full delay distributions and cancellations 1,000 times, reroutes missed
connections to the next option, and reports frequencies.

![Brier scores](img/brier.png)
![Calibration](img/calibration.png)

## Where the model does not do well

- **Tight connections are too optimistic.** By shortest change in the journey:

  | Shortest change | Journeys | Predicted to work | Actually worked |
  |---|---|---|---|
  | ≤ 5 min | 93 | 37.5 % | 26.9 % |
  | 6–10 min | 187 | 65.9 % | 58.8 % |
  | > 10 min | 240 | 86.4 % | 79.6 % |

  Likely causes: leg delays are sampled independently, while in reality a late evening usually means late trains
  everywhere (network-wide disruption); and a 4-minute default change time is short for some stations.
- **Stuttgart → Villingen is the worst pair**: on-time predicted 43 %, observed 29 %. The Gäubahn (RE 87 via Horb)
  was worse in summer 2026 than in spring. The model has no notion of construction periods.
- **Rare events are not modelled**: strikes, storm closures, rail replacement buses. Those show up as stranded
  evenings the model did not see coming.
- **The replay uses the current GTFS feed** for dates in the feed period only (from 2026-05-03). Timetable changes
  within the period are reflected, but not ad-hoc construction changes that were only in the live data.

## 3. Live accuracy

Every prediction the API makes is logged (`predictions`). A nightly job loads yesterday's actual train times from
the raw piebro data and fills `outcomes`; `/api/v1/accuracy` and the *Accuracy* page show Brier scores and
calibration for the last 7/30/90 days. First run (2026-09-22, 30 journeys): connections Brier 0.139 vs. 0.207
timetable-only, a small sample but consistent with the replay.

## Reproduce

```bash
python ml/pipelines/train.py --test-months 2026-07 2026-08
python ml/pipelines/evaluate_replay.py --months 2026-07 2026-08
```
