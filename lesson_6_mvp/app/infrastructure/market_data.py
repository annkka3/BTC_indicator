from __future__ import annotations
import requests

BINANCE_FUT = "https://fapi.binance.com"
BINANCE_SPOT = "https://api.binance.com"

def binance_funding_and_mark(symbol_usdt: str = "BTCUSDT") -> dict:
    # premiumIndex даёт markPrice и fundingRate
    r = requests.get(f"{BINANCE_FUT}/fapi/v1/premiumIndex", params={"symbol": symbol_usdt}, timeout=10)
    r.raise_for_status()
    j = r.json()
    return {"fundingRate": float(j.get("lastFundingRate", 0.0)),
            "markPrice": float(j.get("markPrice", 0.0))}

def binance_spot_price(symbol_usdt: str = "BTCUSDT") -> float:
    r = requests.get(f"{BINANCE_SPOT}/api/v3/ticker/price", params={"symbol": symbol_usdt}, timeout=10)
    r.raise_for_status()
    return float(r.json()["price"])

def basis_pct(symbol_usdt: str="BTCUSDT") -> dict:
    fut = binance_funding_and_mark(symbol_usdt)
    spot = binance_spot_price(symbol_usdt)
    basis = (fut["markPrice"] - spot) / spot * 100.0 if spot>0 else 0.0
    return {"spot": spot, "mark": fut["markPrice"], "fundingRate": fut["fundingRate"], "basis_pct": basis}
