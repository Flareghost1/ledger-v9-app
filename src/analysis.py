# -*- coding: utf-8 -*-
"""
보유종목 단위 분석 헬퍼: 실시간 시세, 전략 신호(현재 액션), what-if 시나리오.
"""
import numpy as np
import pandas as pd
import streamlit as st
import yfinance as yf
from datetime import date, timedelta

from engine import load_data, market_of, run_strategy, regime_label, DEFAULTS

@st.cache_data(ttl=600, show_spinner=False)
def fetch_live_prices(tickers):
    """티커 리스트 → {티커: 최근종가} (실시간에 가까운 지연시세)."""
    out = {}
    for t in tickers:
        try:
            h = yf.download(t, period="5d", progress=False, auto_adjust=True)
            if h.empty:
                out[t] = None; continue
            c = h["Close"].iloc[-1]
            out[t] = float(c.iloc[0]) if hasattr(c, "iloc") else float(c)
        except Exception:
            out[t] = None
    return out

@st.cache_data(ttl=600, show_spinner=False)
def fetch_fx_usdkrw():
    try:
        h = yf.download("KRW=X", period="5d", progress=False, auto_adjust=True)
        c = h["Close"].iloc[-1]
        return float(c.iloc[0]) if hasattr(c, "iloc") else float(c)
    except Exception:
        return 1400.0

@st.cache_data(ttl=1800, show_spinner=False)
def get_history(ticker, years=3):
    end = date.today()
    start = end - timedelta(days=int(365.25 * years))
    return load_data(ticker, str(start), str(end))

def _vxn_of(data):
    return data["vxn"] if "vxn" in data.columns else data["vix"]

@st.cache_data(ttl=600, show_spinner=False)
def latest_signal(ticker, strat_key="full", years=3, **params):
    """해당 종목에 전략을 적용했을 때 '오늘 시점' 권고 비중/국면/최근 룰 이벤트를 반환."""
    data = get_history(ticker, years)
    if data is None or len(data) < 30:
        return None
    df = run_strategy(strat_key, data["date"], data["price"], data["ixic"], data["vix"],
                      vxn=_vxn_of(data), **params)
    last = df.iloc[-1]
    events = df[df.get("rule", "") != ""][["date", "price", "rule"]].tail(5) if "rule" in df.columns else pd.DataFrame()
    return dict(
        df=df, last=last,
        target=float(last["target"]), price=float(last["price"]),
        label=regime_label(last), events=events,
        m3_recent30=int(df["m3"].tail(30).sum()) if "m3" in df.columns else 0,
        peak=float(last.get("peak_nv", df["price"].max())),
        drawdown=float(last["price"] / last.get("peak_nv", df["price"].max()) - 1),
        vix=float(last["vix"]) if pd.notna(last.get("vix")) else None,
        vxn=float(last["vxn"]) if ("vxn" in df.columns and pd.notna(last.get("vxn"))) else None,
    )

@st.cache_data(ttl=600, show_spinner=False)
def whatif_signal(ticker, strat_key="full", years=3, shock_pct=0.0, shock_index=False, **params):
    """가격을 ±shock_pct 만큼 이동시킨 가상의 다음날을 추가해 전략이 어떻게 반응하는지 계산."""
    data = get_history(ticker, years)
    if data is None or len(data) < 30:
        return None
    ext = data.copy()
    new_row = {c: ext[c].iloc[-1] for c in ext.columns}
    new_row["date"] = ext["date"].iloc[-1] + pd.Timedelta(days=1)
    new_row["price"] = ext["price"].iloc[-1] * (1 + shock_pct)
    if shock_index:
        new_row["ixic"] = ext["ixic"].iloc[-1] * (1 + shock_pct)
    ext.loc[len(ext)] = [new_row[c] for c in ext.columns]
    df = run_strategy(strat_key, ext["date"], ext["price"], ext["ixic"], ext["vix"],
                      vxn=_vxn_of(ext), **params)
    before = df.iloc[-2]; after = df.iloc[-1]
    stats = whatif_stats(data, shock_pct, shock_index)
    return dict(df=df, before=before, after=after,
                target_before=float(before["target"]), target_after=float(after["target"]),
                label_before=regime_label(before), label_after=regime_label(after),
                price_before=float(before["price"]), price_after=float(after["price"]),
                stats=stats)

def whatif_stats(data, shock_pct, shock_index):
    """가격 쇼크에 대한 통계적 근거: 과거 유사 급락일 이후 종목의 전방 수익률 분포 등."""
    px = np.asarray(data["price"], float)
    ret_px = np.diff(px) / px[:-1]
    peak = np.maximum.accumulate(px)
    dd_now = px[-1] / peak[-1] - 1                 # 현재 전고점 대비 낙폭
    dd_after = (px[-1] * (1 + shock_pct)) / peak[-1] - 1  # 쇼크 후 낙폭

    # 과거 '유사 급락일' 이후 20거래일 종목 수익률 분포.
    # 전방수익률의 대상은 항상 이 종목이므로 종목 자신의 일간수익률(ret_px)로 유사일을 찾는다.
    # 단, |쇼크|가 커서 단일일 표본이 희박하면 -5%를 하한(floor)으로 완화하고 그 사실을 라벨에 명시.
    fwd, thr = np.array([]), None
    if shock_pct < 0:
        thr = max(shock_pct, -0.03)   # 마삼룰 트리거(-3%)를 하한으로: '단일일 -3% 이하'를 유사일로 집계
        idxs = np.where(ret_px <= thr)[0]
        vals = []
        for i in idxs:
            j0 = i + 1
            j1 = min(j0 + 20, len(px) - 1)
            if j1 > j0:
                vals.append(px[j1] / px[j0] - 1)
        fwd = np.array(vals) if vals else np.array([])
    return dict(
        dd_now=float(dd_now), dd_after=float(dd_after),
        daily_vol=float(np.std(ret_px) * np.sqrt(252)),
        similar_days=int(len(fwd)),
        fwd_mean=float(np.mean(fwd)) if len(fwd) else None,
        fwd_win=float(np.mean(fwd > 0)) if len(fwd) else None,
        fwd_p20=float(np.percentile(fwd, 20)) if len(fwd) else None,
        fwd_p80=float(np.percentile(fwd, 80)) if len(fwd) else None,
        thr=float(thr) if thr is not None else None,
        thr_relaxed=bool(shock_pct < -0.03),
    )

def action_from_target(target_ratio, current_ratio=1.0, tol=0.03):
    """목표비중 대비 실보유비중 차이를 매수/매도/보유 액션으로 변환."""
    diff = current_ratio - target_ratio
    if diff > tol:
        return "🔻 매도", diff
    if diff < -tol:
        return "🔺 매수", -diff
    return "🟰 보유", 0.0
