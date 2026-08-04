# -*- coding: utf-8 -*-
"""
tabs/shared.py — 신한 HTS [1721] 종합계좌 수익률(기간) 스타일 공용 위젯 (v9 §4·§9)

현황 탭과 매매일지 탭이 같은 계산·차트를 재사용한다.
데이터원: asset_snapshots(+detail) = 순자산, 원장 DEPOSIT/WITHDRAW = 입출금.
  일별 손익 = 당일순자산 − 전일순자산 − 기간입금 + 기간출금
  일별 수익률 = 손익 ÷ (전일순자산 + 기간입금)
  기간 수익률 = (1+일별수익률) 누적곱 − 1  (시간가중 근사)
"""
from datetime import date

import pandas as pd
import numpy as np
import plotly.graph_objects as go
import streamlit as st

import snapshots as SNAP
from enums import norm_type


def real_avg_cost_series(ledger, owner_set, asset_id, dates):
    """dates(오름차순 'YYYY-MM-DD' 문자열 리스트)의 각 시점에서, owner_set이 보유한 asset_id의
    실제 평균매입단가(종목 원통화 기준)·수량 시계열. asset_id는 계좌와 무관한 식별자라
    자동으로 여러 계좌를 합산한 값이 된다(v9 §4: 계좌 통합 표시).
    반환: [(qty, avg_cost_or_None), ...] — dates와 같은 길이, 이동평균법(ledger.py replay와 동일 로직)."""
    events = []
    for t in ledger.txns:
        if t["owner"] not in owner_set or t["asset_id"] != asset_id:
            continue
        typ = norm_type(t["type"])
        try:
            q = float(t.get("qty") or 0)
            p = float(t.get("price") or 0)
        except (ValueError, TypeError):
            q, p = 0.0, 0.0
        if typ in ("OPEN_POS", "BUY", "GIFT_IN", "TRANSFER_IN"):
            events.append((t["date"], "add", q, p))
        elif typ in ("SELL", "GIFT_OUT", "TRANSFER_OUT"):
            events.append((t["date"], "remove", q, p))
        elif typ == "SPLIT" and q:
            events.append((t["date"], "split", q, 0))
    events.sort(key=lambda x: x[0])

    out, qty, cost, ei = [], 0.0, 0.0, 0
    for d in dates:
        while ei < len(events) and events[ei][0] <= d:
            _, op, q, p = events[ei]
            if op == "add":
                qty += q
                cost += q * p
            elif op == "remove":
                if qty > 1e-9:
                    cost -= (cost / qty) * q
                qty -= q
            elif op == "split":
                qty *= q   # 총원가는 불변, 평단만 분할비만큼 낮아짐
            ei += 1
        avg_now = (cost / qty) if qty > 1e-9 else None
        out.append((qty, avg_now))
    return out


def _txn_krw(t):
    """거래 1건의 원화 환산 금액(절대값). 원장 replay와 같은 우선순위: amount_ccy → qty×price."""
    try:
        amt = float(t.get("amount_ccy") or t.get("amount") or 0)
    except (ValueError, TypeError):
        amt = 0.0
    if not amt:
        try:
            amt = float(t.get("qty") or 0) * float(t.get("price") or 0)
        except (ValueError, TypeError):
            amt = 0.0
    try:
        fxv = float(t.get("fx") or 1)
    except (ValueError, TypeError):
        fxv = 1.0
    return abs(amt) * fxv


def nav_series(ctx):
    """기간 내 일별 순자산 시계열 [(date_iso, nav)]. 자산군 필터가 켜져 있으면
    상세 스냅샷(자산군별)에서 선택 자산군만 합산, 아니면 총자산 스냅샷."""
    since = ctx.basis_date.isoformat()
    if ctx.class_filter_on:
        detail = SNAP.series_detail(ctx.snap_key, "class", since_iso=since)
        by_date = {}
        for r in detail:
            if r["key"] in ctx.sel_classes:
                by_date[r["date"]] = by_date.get(r["date"], 0.0) + r["value"]
        if len(by_date) >= 2:
            return sorted(by_date.items())
        st.caption("ℹ️ 선택 자산군의 상세 스냅샷 이력이 부족해 총자산 기준으로 표시합니다(상세는 7/25부터 축적).")
    return [(r["date"], r["total"]) for r in SNAP.series(ctx.snap_key, since_iso=since)]


def nav_series_by_class(ctx):
    """기간 내 자산군별 순자산 시계열 (누적영역 그래프용).
    반환: (dates, {자산군: [값...]}) — 상세 스냅샷이 2일 미만이면 None."""
    since = ctx.basis_date.isoformat()
    detail = SNAP.series_detail(ctx.snap_key, "class", since_iso=since)
    if not detail:
        return None
    rows = [r for r in detail if r["key"] in ctx.sel_classes]
    if not rows:
        return None
    dates = sorted({r["date"] for r in rows})
    if len(dates) < 2:
        return None
    keys = sorted({r["key"] for r in rows})
    grid = {k: {d: 0.0 for d in dates} for k in keys}
    for r in rows:
        grid[r["key"]][r["date"]] += r["value"]
    # 합계가 큰 자산군이 아래로 쌓이도록 정렬
    keys.sort(key=lambda k: -sum(grid[k].values()))
    return dates, {k: [grid[k][d] for d in dates] for k in keys}


def perf_table(ctx):
    """신한 [1721] 스타일 일별 테이블 DataFrame + 요약 dict. 데이터 부족 시 (None, None)."""
    nav = nav_series(ctx)
    if len(nav) < 2:
        return None, None
    dates = [d for d, _ in nav]
    # 입출금(DEPOSIT/WITHDRAW)은 '계좌 전체'의 외부 현금 유출입이라, 특정 자산군·종목만 골라본
    # 부분 포트폴리오에는 귀속시킬 수 없다(그러면 전체 입출금이 그 자산군 손익으로 잘못 잡힌다).
    # 필터가 걸린 동안에는 외부 유출입을 0으로 두고, 손익=순자산 변화로만 본다.
    partial = bool(getattr(ctx, "filter_on", False))
    flows = {}   # date_iso -> [dep, wd]
    if not partial:
        for t in ctx.L.txns:
            if t["owner"] not in ctx.owner_set:
                continue
            typ = norm_type(t["type"])
            if typ not in ("DEPOSIT", "WITHDRAW"):
                continue
            d = str(t["date"])
            if d <= dates[0] or d > dates[-1]:
                continue
            krw = _txn_krw(t)
            f = flows.setdefault(d, [0.0, 0.0])
            f[0 if typ == "DEPOSIT" else 1] += krw

    rows = []
    prev_nav = None
    fdates = sorted(flows.keys())
    fi = 0
    for i, (d, v) in enumerate(nav):
        dep = wd = 0.0
        while fi < len(fdates) and fdates[fi] <= d:
            dep += flows[fdates[fi]][0]
            wd += flows[fdates[fi]][1]
            fi += 1
        if i == 0:
            rows.append(dict(날짜=d, 순자산=v, 입금=0.0, 출금=0.0, 손익=np.nan, 수익률=np.nan))
        else:
            pnl = v - prev_nav - dep + wd
            base = prev_nav + dep
            ret = pnl / base if base else np.nan
            rows.append(dict(날짜=d, 순자산=v, 입금=dep, 출금=wd, 손익=pnl, 수익률=ret))
        prev_nav = v
    df = pd.DataFrame(rows)
    df["누적손익"] = df["손익"].fillna(0).cumsum()
    df["누적수익률"] = (1 + df["수익률"].fillna(0)).cumprod() - 1

    dep_sum = df["입금"].sum()
    wd_sum = df["출금"].sum()
    start_nav, end_nav = df["순자산"].iloc[0], df["순자산"].iloc[-1]
    pnl_sum = end_nav - start_nav - dep_sum + wd_sum
    base = start_nav + dep_sum
    summ = dict(start_date=df["날짜"].iloc[0], end_date=df["날짜"].iloc[-1],
                start_nav=start_nav, end_nav=end_nav, deposits=dep_sum, withdrawals=wd_sum,
                pnl=pnl_sum, ret=(pnl_sum / base if base else 0.0),
                twr=df["누적수익률"].iloc[-1], partial=partial)
    return df, summ


def render_perf(ctx, key, events=None, show_table=True):
    """신한 [1721] 스타일 전체 렌더: 요약 6칸 + 전환형 차트 + 일별 테이블.
    events: [{no, date, label, kind}] → 차트에 번호 마커(매매일지 §9). 반환: perf df(없으면 None)."""
    df, summ = perf_table(ctx)
    if df is None:
        st.info(f"'{ctx.owner_label}' 스냅샷이 기간 내 2일 미만입니다 — 앱을 매일 열면 하루씩 쌓여 "
                "기간 수익률 화면이 채워집니다.")
        return None

    if summ.get("partial"):
        st.caption("🗂 사이드바 필터가 걸려 있어 **선택 항목만**의 수익률입니다. 입출금은 계좌 전체 기준이라 "
                   "특정 자산군에 귀속시킬 수 없어 0으로 두고, 손익은 순자산 변화로만 계산합니다. "
                   "전체 기준 입출금·수익률을 보려면 사이드바에서 '전체선택'을 누르세요.")
    c = st.columns(6)
    c[0].metric("시작시점 순자산", f"₩{summ['start_nav']:,.0f}", summ["start_date"], delta_color="off")
    c[1].metric("입금고액", f"₩{summ['deposits']:,.0f}", "필터 중 미집계" if summ.get("partial") else None,
                delta_color="off")
    c[2].metric("출금고액", f"₩{summ['withdrawals']:,.0f}", "필터 중 미집계" if summ.get("partial") else None,
                delta_color="off")
    c[3].metric("평가시점 순자산", f"₩{summ['end_nav']:,.0f}", summ["end_date"], delta_color="off")
    c[4].metric("투자손익", f"₩{summ['pnl']:,.0f}",
                f"{summ['pnl']:+,.0f}원" if summ["pnl"] else None)
    c[5].metric("수익률(기간)", f"{summ['ret']:+.2%}", f"시간가중 {summ['twr']:+.2%}", delta_color="off")

    mode = st.pills("차트", ["잔고추이", "손익(기간별)", "손익(누적)", "수익률(누적)"],
                    default="잔고추이", selection_mode="single", key=f"{key}_mode") or "잔고추이"
    fig = go.Figure()
    x = df["날짜"]
    if mode == "잔고추이":
        # 자산군별 누적영역(스택) — 상세 스냅샷이 있으면 구성까지 보여준다.
        stacked = nav_series_by_class(ctx)
        if stacked:
            sdates, series = stacked
            for cls, vals in series.items():
                fig.add_trace(go.Scatter(x=sdates, y=vals, name=cls, mode="lines",
                                         stackgroup="nav", line=dict(width=0.5),
                                         hovertemplate="%{x}<br>" + cls + " ₩%{y:,.0f}<extra></extra>"))
            totals = [sum(vals[i] for vals in series.values()) for i in range(len(sdates))]
            fig.add_trace(go.Scatter(x=sdates, y=totals, name="합계", mode="lines",
                                     line=dict(color="#111827", width=2),
                                     hovertemplate="%{x}<br>합계 ₩%{y:,.0f}<extra></extra>"))
            ybase = pd.Series(totals, index=sdates)
        else:
            fig.add_trace(go.Scatter(x=x, y=df["순자산"], name="순자산", mode="lines+markers",
                                     line=dict(color="#2980b9", width=2), fill="tozeroy",
                                     fillcolor="rgba(41,128,185,0.08)"))
            st.caption("ℹ️ 자산군별 상세 스냅샷이 부족해 총자산 선으로 표시합니다(상세는 2026-07-25부터 축적).")
            ybase = df.set_index("날짜")["순자산"]
        fig.update_layout(yaxis_title="순자산(원)")
    elif mode == "손익(기간별)":
        pnl = df["손익"].fillna(0)
        fig.add_trace(go.Bar(x=x, y=pnl, name="일별 손익",
                             marker_color=["#16a34a" if v >= 0 else "#dc2626" for v in pnl]))
        fig.update_layout(yaxis_title="손익(원)")
        ybase = df.set_index("날짜")["손익"].fillna(0)
    elif mode == "손익(누적)":
        fig.add_trace(go.Bar(x=x, y=df["누적손익"], name="누적 손익",
                             marker_color=["#16a34a" if v >= 0 else "#dc2626" for v in df["누적손익"]]))
        fig.update_layout(yaxis_title="누적 손익(원)")
        ybase = df.set_index("날짜")["누적손익"]
    else:
        fig.add_trace(go.Scatter(x=x, y=df["누적수익률"] * 100, name="누적 수익률",
                                 mode="lines+markers", line=dict(color="#7c3aed", width=2)))
        fig.update_layout(yaxis_title="누적 수익률(%)")
        ybase = df.set_index("날짜")["누적수익률"] * 100

    # §9: 이벤트 발생일 번호 마커 (그래프 ↔ 테이블 번호 연결)
    # 누적영역 모드에서는 x축 날짜 집합이 달라질 수 있어, 실제 그려진 축(ybase)의 날짜를 쓴다.
    if events:
        snap_dates = [str(d) for d in ybase.index]
        by_snap = {}
        for ev in events:
            d = next((sd for sd in snap_dates if sd >= ev["date"]), None)
            if d is None:
                continue
            by_snap.setdefault(d, []).append(ev)
        if by_snap:
            mx, my, mtext, mhover = [], [], [], []
            for d, evs in sorted(by_snap.items()):
                mx.append(d)
                my.append(float(ybase.get(d, 0)))
                mtext.append(",".join(str(e["no"]) for e in evs))
                mhover.append("<br>".join(f"#{e['no']} {e['date']} {e['label']}" for e in evs))
            fig.add_trace(go.Scatter(x=mx, y=my, mode="markers+text", name="이벤트",
                                     text=mtext, textposition="top center",
                                     textfont=dict(size=10, color="#b45309"),
                                     marker=dict(symbol="circle", size=9, color="#f59e0b",
                                                 line=dict(color="#92400e", width=1)),
                                     hovertext=mhover, hoverinfo="text"))
    fig.update_layout(height=380, margin=dict(l=10, r=10, t=30, b=10),
                      legend=dict(orientation="h", y=-0.25),
                      title=f"{ctx.owner_label} {mode} — {summ['start_date']} ~ {summ['end_date']}")
    st.plotly_chart(fig, width="stretch", key=f"{key}_chart")

    if show_table:
        with st.expander(f"📋 일별 테이블 ({len(df)}일)", expanded=False):
            tdf = df[["날짜", "순자산", "입금", "출금", "손익", "수익률", "누적손익", "누적수익률"]].copy()
            tdf["수익률"] *= 100
            tdf["누적수익률"] *= 100
            st.dataframe(tdf, width="stretch", hide_index=True, height=330, column_config={
                "순자산": st.column_config.NumberColumn(format="₩%,.0f"),
                "입금": st.column_config.NumberColumn(format="₩%,.0f"),
                "출금": st.column_config.NumberColumn(format="₩%,.0f"),
                "손익": st.column_config.NumberColumn(format="₩%,.0f"),
                "수익률": st.column_config.NumberColumn(format="%+.2f%%"),
                "누적손익": st.column_config.NumberColumn(format="₩%,.0f"),
                "누적수익률": st.column_config.NumberColumn(format="%+.2f%%"),
            })
    st.caption("일별 손익 = 당일순자산 − 전일순자산 − 입금 + 출금 · 수익률 = 손익 ÷ (전일순자산+입금). "
               "입출금은 원장의 DEPOSIT/WITHDRAW 기준(자산군 필터와 무관하게 전체 현금 기준). "
               "순자산은 매일 앱을 열 때 기록되는 시가 스냅샷입니다.")
    return df
