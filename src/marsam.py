# -*- coding: utf-8 -*-
"""
marsam.py — 마삼룰 상태머신 (SPEC §5, 우선순위 5)
나스닥 종합지수(^IXIC) 일간수익률 기준으로 현재 국면을 판정한다.
  HOLD    : 정상 보유
  WAIT_B  : -3% 발생 → 대기 (마지막 -3%일 +1개월+1일)
  WAIT_E  : 1개월 내 -3% 4회(공황) → 마지막 -3%일 +2개월+1일 대기
매매 레벨(말뚝박기 단계)은 기준종목(기본 NVDA)의 전고점 대비 낙폭으로 계산.
정밀 백테스트/시뮬레이션은 v6 엔진(engine.run_engine)을 재사용한다.
"""
from datetime import date, timedelta
import pandas as pd
import numpy as np
from prices import history

M3 = -0.03
PANIC_N = 4

def state(nasdaq_years=1, anchor_ticker="NVDA", today=None):
    """현재 마삼룰 국면과 근거 수치를 반환."""
    nq = history("^IXIC", years=nasdaq_years)
    if nq is None or len(nq) < 30:
        return dict(state="UNKNOWN", detail="나스닥 데이터 조회 실패")
    nq = nq.reset_index(drop=True)
    px = nq["price"].values
    dates = pd.to_datetime(nq["date"])
    ret = np.zeros(len(px)); ret[1:] = px[1:]/px[:-1] - 1
    m3_idx = [i for i in range(len(px)) if ret[i] <= M3]
    last_m3 = dates.iloc[m3_idx[-1]] if m3_idx else None

    today = pd.Timestamp(today) if today else dates.iloc[-1]
    # 최근 1개월 내 -3% 횟수
    recent = [i for i in m3_idx if (today - dates.iloc[i]).days <= 30]
    panic = len(recent) >= PANIC_N

    st = "HOLD"; wait_until = None
    if last_m3 is not None:
        base_wait = (2 if panic else 1)
        wu = last_m3 + pd.DateOffset(months=base_wait) + pd.Timedelta(days=1)
        if today < wu:
            st = "WAIT_E" if panic else "WAIT_B"
            wait_until = wu

    # 8거래일 연속상승 → 조기 복귀 신호
    up_streak = 0
    for i in range(len(px)-1, 0, -1):
        if px[i] > px[i-1]: up_streak += 1
        else: break

    # 기준종목 낙폭 → 말뚝 단계
    anc = history(anchor_ticker, years=nasdaq_years)
    stage = None; anc_dd = None
    if anc is not None and len(anc) > 5:
        ap = anc["price"].values
        peak = np.maximum.accumulate(ap)
        anc_dd = ap[-1]/peak[-1] - 1
        stage = int(max(0.0, -anc_dd) / 0.025)

    return dict(
        state=st,
        wait_until=wait_until.strftime("%Y-%m-%d") if wait_until is not None else None,
        last_m3=last_m3.strftime("%Y-%m-%d") if last_m3 is not None else None,
        m3_recent_30d=len(recent), panic=panic, up_streak=int(up_streak),
        anchor=anchor_ticker, anchor_drawdown=float(anc_dd) if anc_dd is not None else None,
        stage=stage, nasdaq_today_ret=float(ret[-1]),
        detail=_detail(st, len(recent), last_m3, wait_until, up_streak),
    )

def _detail(st, n30, last_m3, wait_until, up_streak):
    if st == "HOLD":
        base = "상태 HOLD (정상 보유)"
        if last_m3 is not None:
            base += f" · 마지막 −3% {last_m3.strftime('%Y-%m-%d')}"
        else:
            base += " · 최근 −3% 트리거 없음"
        if up_streak >= 8:
            base += f" · {up_streak}일 연속상승(조기 재매수 신호)"
        return base
    if st == "WAIT_B":
        return f"⚠️ WAIT_B (−3% 대기) · 해제 예정 {wait_until.strftime('%Y-%m-%d')}"
    if st == "WAIT_E":
        return f"🚨 WAIT_E (공황·1개월내 −3% {n30}회) · 해제 예정 {wait_until.strftime('%Y-%m-%d')}"
    return "상태 판정 불가"
