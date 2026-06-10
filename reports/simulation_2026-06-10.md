# Historical simulation — deterministic strategy, last 6 weeks

- Trading days: 30 | entry scans: 579
- Capital: ₹50,000 → **₹45,811** (-8.4%)
- Trades: 39 | win rate: 51% | profit factor: 0.83
- Avg win: ₹1,011 | avg loss: ₹-1,284
- Max drawdown: ₹12,185 (24.4% of capital)
- Total charges paid: ₹3,900

## By strategy
| Strategy | Trades | P&L |
|---|---|---|
| BEAR_CALL_SPREAD | 8 | ₹316 |
| BEAR_PUT_SPREAD | 25 | ₹1,905 |
| BULL_CALL_SPREAD | 4 | ₹-3,198 |
| BULL_PUT_SPREAD | 2 | ₹-3,213 |

## Trades
| Date | Strategy | Entry | Exit | Reason | P&L |
|---|---|---|---|---|---|
| 2026-04-28 | BULL_PUT_SPREAD | 10:15 | 11:15 | credit stop | ₹-3,376 |
| 2026-05-05 | BULL_PUT_SPREAD | 13:00 | 14:15 | profit take | ₹163 |
| 2026-05-07 | BULL_CALL_SPREAD | 09:30 | 15:15 | square-off | ₹-797 |
| 2026-05-07 | BULL_CALL_SPREAD | 10:15 | 15:15 | square-off | ₹-464 |
| 2026-05-08 | BULL_CALL_SPREAD | 14:30 | 15:15 | square-off | ₹-730 |
| 2026-05-11 | BEAR_PUT_SPREAD | 09:30 | 11:30 | stop loss | ₹-1,542 |
| 2026-05-11 | BEAR_PUT_SPREAD | 10:15 | 11:30 | stop loss | ₹-1,461 |
| 2026-05-12 | BEAR_CALL_SPREAD | 10:15 | 11:15 | profit take | ₹404 |
| 2026-05-12 | BEAR_CALL_SPREAD | 11:00 | 12:00 | profit take | ₹639 |
| 2026-05-12 | BEAR_CALL_SPREAD | 11:45 | 12:00 | profit take | ₹594 |
| 2026-05-12 | BEAR_CALL_SPREAD | 12:30 | 13:30 | profit take | ₹321 |
| 2026-05-19 | BEAR_CALL_SPREAD | 12:30 | 13:00 | profit take | ₹435 |
| 2026-05-26 | BULL_CALL_SPREAD | 09:30 | 09:45 | stop loss | ₹-1,207 |
| 2026-05-26 | BEAR_PUT_SPREAD | 12:00 | 13:00 | target | ₹1,325 |
| 2026-05-26 | BEAR_PUT_SPREAD | 12:45 | 13:15 | trail stop | ₹144 |
| 2026-05-27 | BEAR_PUT_SPREAD | 09:30 | 15:15 | square-off | ₹-336 |
| 2026-05-27 | BEAR_PUT_SPREAD | 12:45 | 15:15 | square-off | ₹-360 |
| 2026-05-29 | BEAR_PUT_SPREAD | 12:00 | 15:15 | square-off | ₹2,410 |
| 2026-05-29 | BEAR_PUT_SPREAD | 12:45 | 15:15 | square-off | ₹2,436 |
| 2026-06-01 | BEAR_PUT_SPREAD | 09:30 | 12:00 | trail stop | ₹752 |
| 2026-06-01 | BEAR_PUT_SPREAD | 10:15 | 15:15 | square-off | ₹3,146 |
| 2026-06-01 | BEAR_PUT_SPREAD | 12:00 | 15:15 | square-off | ₹2,987 |
| 2026-06-02 | BEAR_PUT_SPREAD | 09:30 | 10:15 | stop loss | ₹-1,918 |
| 2026-06-02 | BEAR_PUT_SPREAD | 10:45 | 11:15 | stop loss | ₹-1,334 |
| 2026-06-03 | BEAR_PUT_SPREAD | 09:30 | 14:30 | stop loss | ₹-1,688 |
| 2026-06-03 | BEAR_PUT_SPREAD | 10:15 | 14:15 | stop loss | ₹-1,634 |
| 2026-06-04 | BEAR_PUT_SPREAD | 12:30 | 15:15 | square-off | ₹-717 |
| 2026-06-04 | BEAR_PUT_SPREAD | 13:15 | 15:15 | square-off | ₹-913 |
| 2026-06-05 | BEAR_PUT_SPREAD | 09:45 | 14:30 | trail stop | ₹295 |
| 2026-06-05 | BEAR_PUT_SPREAD | 10:30 | 15:15 | square-off | ₹-303 |
| 2026-06-05 | BEAR_PUT_SPREAD | 14:30 | 15:15 | square-off | ₹141 |
| 2026-06-08 | BEAR_PUT_SPREAD | 09:30 | 12:15 | stop loss | ₹-1,293 |
| 2026-06-08 | BEAR_PUT_SPREAD | 10:15 | 12:30 | stop loss | ₹-1,338 |
| 2026-06-08 | BEAR_PUT_SPREAD | 12:15 | 14:30 | trail stop | ₹593 |
| 2026-06-09 | BEAR_CALL_SPREAD | 09:45 | 10:45 | profit take | ₹626 |
| 2026-06-09 | BEAR_CALL_SPREAD | 11:00 | 14:30 | credit stop | ₹-2,995 |
| 2026-06-09 | BEAR_CALL_SPREAD | 11:45 | 13:45 | profit take | ₹290 |
| 2026-06-10 | BEAR_PUT_SPREAD | 12:30 | 15:15 | square-off | ₹1,021 |
| 2026-06-10 | BEAR_PUT_SPREAD | 13:15 | 15:15 | square-off | ₹1,490 |

## Caveats (read before acting on this)
- Option premiums are Black-Scholes-synthesised from real NIFTY/VIX data; real premiums carry skew, smile and microstructure this cannot capture.
- Signals tested: daily trend + intraday momentum (the technical core). Option-chain positioning, FII/DII and news components are not reconstructable historically and are absent here.
- Slippage 0.25%/side and ₹25/order charges are estimates.
- Weekly expiry assumed on weekday 1 (Tuesday).
- A few weeks is a small sample; treat this as a sanity gauge, not a guarantee.
