# Historical simulation — deterministic strategy, last 6 weeks

- Trading days: 30 | entry scans: 593
- Capital: ₹50,000 → **₹47,497** (-5.0%)
- Trades: 33 | win rate: 52% | profit factor: 0.88
- Avg win: ₹1,042 | avg loss: ₹-1,264
- Max drawdown: ₹11,219 (22.4% of capital)
- Total charges paid: ₹3,300

## By strategy
| Strategy | Trades | P&L |
|---|---|---|
| BEAR_CALL_SPREAD | 6 | ₹272 |
| BEAR_PUT_SPREAD | 23 | ₹736 |
| BULL_CALL_SPREAD | 2 | ₹-1,937 |
| BULL_PUT_SPREAD | 2 | ₹-1,574 |

## Trades
| Date | Strategy | Entry | Exit | Reason | P&L |
|---|---|---|---|---|---|
| 2026-04-28 | BULL_PUT_SPREAD | 10:30 | 11:15 | credit stop | ₹-1,737 |
| 2026-05-05 | BULL_PUT_SPREAD | 13:00 | 14:15 | profit take | ₹163 |
| 2026-05-08 | BULL_CALL_SPREAD | 14:30 | 15:15 | square-off | ₹-730 |
| 2026-05-11 | BEAR_PUT_SPREAD | 09:30 | 11:30 | stop loss | ₹-1,542 |
| 2026-05-11 | BEAR_PUT_SPREAD | 10:15 | 11:30 | stop loss | ₹-1,461 |
| 2026-05-12 | BEAR_CALL_SPREAD | 10:45 | 12:00 | profit take | ₹626 |
| 2026-05-12 | BEAR_CALL_SPREAD | 12:30 | 13:30 | profit take | ₹321 |
| 2026-05-19 | BEAR_CALL_SPREAD | 12:30 | 13:00 | profit take | ₹435 |
| 2026-05-26 | BULL_CALL_SPREAD | 09:30 | 09:45 | stop loss | ₹-1,207 |
| 2026-05-26 | BEAR_PUT_SPREAD | 12:00 | 13:00 | target | ₹1,325 |
| 2026-05-26 | BEAR_PUT_SPREAD | 12:45 | 13:15 | trail stop | ₹144 |
| 2026-05-27 | BEAR_PUT_SPREAD | 09:45 | 15:15 | square-off | ₹-619 |
| 2026-05-29 | BEAR_PUT_SPREAD | 12:15 | 15:00 | target | ₹3,470 |
| 2026-05-29 | BEAR_PUT_SPREAD | 13:00 | 15:00 | target | ₹2,599 |
| 2026-06-01 | BEAR_PUT_SPREAD | 09:30 | 12:00 | trail stop | ₹752 |
| 2026-06-01 | BEAR_PUT_SPREAD | 10:15 | 14:15 | target | ₹2,798 |
| 2026-06-01 | BEAR_PUT_SPREAD | 12:00 | 14:15 | target | ₹2,638 |
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
| 2026-06-09 | BEAR_CALL_SPREAD | 10:00 | 11:00 | profit take | ₹341 |
| 2026-06-09 | BEAR_CALL_SPREAD | 11:15 | 12:15 | credit stop | ₹-1,784 |
| 2026-06-09 | BEAR_CALL_SPREAD | 12:00 | 13:45 | profit take | ₹332 |
| 2026-06-10 | BEAR_PUT_SPREAD | 14:00 | 15:15 | square-off | ₹739 |

## Caveats (read before acting on this)
- Option premiums are Black-Scholes-synthesised from real NIFTY/VIX data; real premiums carry skew, smile and microstructure this cannot capture.
- Signals tested: daily trend + intraday momentum (the technical core). Option-chain positioning, FII/DII and news components are not reconstructable historically and are absent here.
- Slippage 0.25%/side and ₹25/order charges are estimates.
- Weekly expiry assumed on weekday 1 (Tuesday).
- A few weeks is a small sample; treat this as a sanity gauge, not a guarantee.
