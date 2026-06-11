"""Shared constants for Dhan API segments and well-known security ids."""

# Dhan exchange segments
IDX_I = "IDX_I"          # indices (spot)
NSE_FNO = "NSE_FNO"      # NSE futures & options

# Well-known Dhan security ids (index spot)
NIFTY_50 = 13
BANKNIFTY = 25
INDIA_VIX = 21

# Option types
CE = "CE"
PE = "PE"

BUY = "BUY"
SELL = "SELL"

# Strategy names
LONG_CALL = "LONG_CALL"
LONG_PUT = "LONG_PUT"
BULL_CALL_SPREAD = "BULL_CALL_SPREAD"
BEAR_PUT_SPREAD = "BEAR_PUT_SPREAD"
BULL_PUT_SPREAD = "BULL_PUT_SPREAD"
BEAR_CALL_SPREAD = "BEAR_CALL_SPREAD"
IRON_CONDOR = "IRON_CONDOR"
NO_TRADE = "NO_TRADE"

DEBIT_STRATEGIES = {LONG_CALL, LONG_PUT, BULL_CALL_SPREAD, BEAR_PUT_SPREAD}
CREDIT_STRATEGIES = {BULL_PUT_SPREAD, BEAR_CALL_SPREAD, IRON_CONDOR}

# Market view labels
BULLISH = "BULLISH"
BEARISH = "BEARISH"
NEUTRAL = "NEUTRAL"

VOL_HIGH = "HIGH"
VOL_NORMAL = "NORMAL"
VOL_LOW = "LOW"

# Dhan scrip master (compact, SEM_* schema) — resolves option contract
# security ids and the authoritative lot size. The parser also tolerates the
# detailed master's column names as a fallback.
SCRIP_MASTER_URL = "https://images.dhan.co/api-data/api-scrip-master.csv"
