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

@lru_cache(maxsize=16)
def fx_rate(ccy):
    """1 <ccy>당 원화. USD 외 통화(BRL 등)는 KRW=X와 <ccy>=X를 교차계산한다.
    yfinance의 '<ccy>=X'는 USD당 해당통화 수량이므로, 원/외화 = (원/달러) ÷ (외화/달러).
    조회 실패 시 None — 호출부가 원가 표시로 폴백하도록 한다(임의값으로 평가액을 지어내지 않는다)."""
    ccy = (ccy or "KRW").upper()
    if ccy == "KRW":
        return 1.0
    if ccy == "USD":
        return fx_usdkrw()
    try:
        h = yf.download(f"{ccy}=X", period="5d", progress=False, auto_adjust=True)
        c = h["Close"]
        s = c.iloc[:, 0] if isinstance(c, pd.DataFrame) else c
        s = s.dropna()
        if s.empty:
            return None
        per_usd = float(s.iloc[-1])
        return fx_usdkrw() / per_usd if per_usd else None
    except Exception:
        return None

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
    # 외화 환산 배율. USD는 호출부가 넘긴 값을 그대로 쓰고(화면 전체가 같은 환율을 쓰도록),
    # BRL 같은 그 외 통화는 교차환율을 조회한다. 조회 실패(None)면 아래에서 원가로 폴백한다
    # — 브라질국채를 원가 그대로 보여주던 문제가 여기서 왔다(USD만 환산하고 BRL은 ×1).
    if ccy == "USD":
        mult = fx
    elif ccy == "KRW":
        mult = 1.0
    else:
        mult = fx_rate(ccy)
    if t and mult is not None:
        cp = live_price(t)
        if cp is not None:
            v = p["qty"] * cp * mult
            return v, cp, True
    # manual: REVALUE 거래로 갱신된 평가단가(revalue_price)가 있으면 그걸 쓰고,
    # 없으면 원장 평단(=취득원가)을 그대로 쓴다(갱신 이력이 없는 자산의 기본값).
    # cost_krw(취득원가)는 여기서 절대 건드리지 않는다 — 실현손익·세금·매매일지 원가추이
    # 차트가 전부 취득원가 기준이라, 평가만 갈아끼우고 원가는 그대로 보존해야 한다.
    rp = p.get("revalue_price")
    if rp is not None and p["qty"] and mult is not None:
        v = p["qty"] * rp * mult
        return v, rp, False
    v = p["cost_krw"] if p["qty"] else 0.0
    cp = p.get("avg_cost")
    return v, cp, False
