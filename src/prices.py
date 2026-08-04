# -*- coding: utf-8 -*-
"""
prices.py — 시세·환율 조회 (SPEC §src, 우선순위 2)
yfinance 기반. price_source가 'yfinance:<티커>'인 자산만 실시간 조회하고,
'manual'/'face_value'는 원장의 최근 단가(평가액)를 그대로 쓴다.
"""
from functools import lru_cache
import yfinance as yf
import pandas as pd

def ticker_of(price_source):
    if price_source and price_source.startswith("yfinance:"):
        return price_source.split(":", 1)[1]
    return None

@lru_cache(maxsize=256)
def live_price(ticker):
    """최근 종가(지연시세). 실패 시 None.
    yfinance가 장 마감 전/휴장일 등에 오늘자 빈 행(Close=NaN, Volume만 있음)을
    맨 끝에 얹어 보낼 때가 있다 — 그걸 그대로 쓰면 이 종목 하나 때문에 포지션
    평가액은 물론 총자산까지 NaN으로 전파된다(실제 재현됨). 유효한 마지막 값만 쓴다."""
    try:
        h = yf.download(ticker, period="5d", progress=False, auto_adjust=True)
        if h.empty:
            return None
        c = h["Close"]
        s = c.iloc[:, 0] if isinstance(c, pd.DataFrame) else c
        s = s.dropna()
        if s.empty:
            return None
        return float(s.iloc[-1])
    except Exception:
        return None

@lru_cache(maxsize=8)
def fx_usdkrw():
    try:
        h = yf.download("KRW=X", period="5d", progress=False, auto_adjust=True)
        c = h["Close"]
        s = c.iloc[:, 0] if isinstance(c, pd.DataFrame) else c
        s = s.dropna()
        if s.empty:
            return 1400.0
        return float(s.iloc[-1])
    except Exception:
        return 1400.0

@lru_cache(maxsize=64)
def history(ticker, years=2):
    from datetime import date, timedelta
    end = date.today(); start = end - timedelta(days=int(365.25*years))
    try:
        h = yf.download(ticker, start=str(start), end=str(end), progress=False, auto_adjust=True)
        if h.empty:
            return None
        c = h["Close"]
        s = c.iloc[:, 0] if isinstance(c, pd.DataFrame) else c
        return pd.DataFrame({"date": s.index, "price": s.values})
    except Exception:
        return None

@lru_cache(maxsize=4)
def index_snapshot(symbol="^IXIC"):
    """지수 최근값 + 전일대비. (마삼룰/시장 스냅샷용)"""
    try:
        h = yf.download(symbol, period="10d", progress=False, auto_adjust=True)
        c = h["Close"]
        s = c.iloc[:, 0] if isinstance(c, pd.DataFrame) else c
        s = s.dropna()
        if len(s) < 2:
            return dict(value=None, change=None)
        last, prev = float(s.iloc[-1]), float(s.iloc[-2])
        return dict(value=last, change=last/prev - 1)
    except Exception:
        return dict(value=None, change=None)

def value_position(p, fx):
    """포지션 1건의 실시간 평가액(원)과 현재가. price_source에 따라 분기.
    반환: (value_krw, cur_price_native_or_None, live_ok)"""
    t = ticker_of(p.get("price_source"))
    ccy = p.get("ccy", "KRW")
    if t:
        cp = live_price(t)
        if cp is not None:
            v = p["qty"] * cp * (fx if ccy == "USD" else 1)
            return v, cp, True
    # manual: REVALUE 거래로 갱신된 평가단가(revalue_price)가 있으면 그걸 쓰고,
    # 없으면 원장 평단(=취득원가)을 그대로 쓴다(갱신 이력이 없는 자산의 기본값).
    # cost_krw(취득원가)는 여기서 절대 건드리지 않는다 — 실현손익·세금·매매일지 원가추이
    # 차트가 전부 취득원가 기준이라, 평가만 갈아끼우고 원가는 그대로 보존해야 한다.
    rp = p.get("revalue_price")
    if rp is not None and p["qty"]:
        v = p["qty"] * rp * (fx if ccy == "USD" else 1)
        return v, rp, False
    v = p["cost_krw"] if p["qty"] else 0.0
    cp = p.get("avg_cost")
    return v, cp, False
