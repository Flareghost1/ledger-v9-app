# -*- coding: utf-8 -*-
"""🚦 액션추천 (v9 §12~14)
- §12 종목별 적용 전략 default 저장(settings.json 'strategy_defaults'). 미선택="전략없음"=계산 제외
- §13 매수/매도 액션 → 원클릭 액션아이템 등록
- §14 종목 주가 트렌드 차트: 실제 매매 마커(▲매수/▼매도, hover에 note/thesis) + 전략 시그널 마커 오버레이
"""
from datetime import date

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import prices
import settings as SET
import action_items as AI
import gdrive_sync as GDRIVE
import engine as v6
from analysis import latest_signal, action_from_target
from enums import norm_type
from tabs import shared

NO_STRAT = "전략없음"


def render(ctx):
    # 사이드바 전역 필터(소유자·자산군·종목)를 반영한 상장 종목만 대상으로 한다.
    tradable = [p for p in ctx.pos_f if p["_live"]]
    if not tradable:
        st.info(f"{ctx.owner_label} · 선택된 자산군·종목 중 실시간 시세 추적 가능한(상장) 종목이 "
                "없습니다. 사이드바 필터를 확인하세요.")
        return
    if ctx.filter_on:
        st.caption("🗂 사이드바 필터 적용 중 — 선택된 종목만 계산·표시됩니다.")

    strat_names = list(v6.STRATS.keys())
    strat_defaults = ctx.SETTINGS.get("strategy_defaults", {})

    for p in tradable:
        p["_ticker"] = prices.ticker_of(p["price_source"])
        p["_label"] = f"{p['name']} ({p['account']}·{p['_ticker']})"

    # ── §12 종목별 전략 (default = settings.json 저장값) ──
    st.markdown("##### 📌 종목별 적용 전략")
    st.caption("종목마다 전략을 고르고 '기본값으로 저장'하면 다음부터 자동 적용됩니다. "
               f"'{NO_STRAT}'인 종목은 액션 계산에서 제외됩니다.")
    edit_src = pd.DataFrame([dict(
        _aid=p["asset_id"], 종목=p["_label"],
        전략=strat_defaults.get(p["asset_id"], NO_STRAT),
        **{"실제투자비중(%)": 100},
    ) for p in tradable])
    edited = st.data_editor(
        edit_src,
        column_order=("종목", "전략", "실제투자비중(%)"),
        column_config={
            "종목": st.column_config.TextColumn(disabled=True, width="large"),
            "전략": st.column_config.SelectboxColumn(options=[NO_STRAT] + strat_names,
                                                     help="종목별 적용 전략. 전략없음=계산 제외"),
            "실제투자비중(%)": st.column_config.NumberColumn(
                min_value=0, max_value=100, step=5,
                help="이미 일부 매도/현금화했다면 현재 실제 주식비중(%). 기본 100(전량 보유)"),
        },
        hide_index=True, width="stretch", key="v9_action_editor")

    b1, b2 = st.columns([1, 3])
    if b1.button("💾 전략 구성을 기본값으로 저장", key="v9_strat_save"):
        new_map = {r["_aid"]: r["전략"] for _, r in edited.iterrows() if r["전략"] != NO_STRAT}
        ctx.SETTINGS["strategy_defaults"] = new_map
        SET.save_settings(ctx.SETTINGS)
        GDRIVE.autopush_toast("settings.json")
        st.success(f"저장 완료 — {len(new_map)}개 종목에 전략 기본값 지정.")
    b2.caption("⚠️ 마삼룰은 '세계 시총 1위 종목' 전제 전략입니다. 그 외 종목 적용 결과는 참고용입니다.")

    # ── 액션 계산 + §13 원클릭 액션아이템 등록 ──
    st.markdown("##### 🚦 오늘의 액션")
    results = []
    for i, p in enumerate(tradable):
        r = edited.iloc[i]
        if r["전략"] == NO_STRAT:
            continue
        skey = v6.STRATS.get(r["전략"])
        sig = latest_signal(p["_ticker"], skey, years=2)
        if sig is None:
            continue
        cur_ratio = r["실제투자비중(%)"] / 100
        action, amt_ratio = action_from_target(sig["target"], cur_ratio)
        amt_krw = amt_ratio * p["_v"]
        results.append(dict(p=p, strat=r["전략"], sig=sig, action=action,
                            amt_krw=amt_krw, cur_ratio=cur_ratio))
    if not results:
        st.info(f"전략이 지정된 종목이 없습니다. 위 표에서 전략을 고르세요('{NO_STRAT}'은 제외).")
    else:
        hdr = st.columns([3, 2, 2, 1.2, 1.2, 1.5, 2, 1.5])
        for c, t in zip(hdr, ["종목", "전략", "국면", "목표비중", "실제비중", "액션", "권고금액", "등록"]):
            c.markdown(f"**{t}**")
        n_buy = n_sell = 0
        for j, r in enumerate(results):
            p, sig = r["p"], r["sig"]
            cols = st.columns([3, 2, 2, 1.2, 1.2, 1.5, 2, 1.5])
            cols[0].write(p["_label"])
            cols[1].write(r["strat"].split(" ", 1)[-1])
            cols[2].write(sig["label"])
            cols[3].write(f"{sig['target']:.0%}")
            cols[4].write(f"{r['cur_ratio']:.0%}")
            act = r["action"]
            color = "#dc2626" if "매도" in act else ("#16a34a" if "매수" in act else "#6b7280")
            cols[5].markdown(f"<span style='color:{color};font-weight:600'>{act}</span>", unsafe_allow_html=True)
            cols[6].write(f"₩{r['amt_krw']:,.0f}" if r["amt_krw"] > 0 else "-")
            if "매수" in act or "매도" in act:
                n_buy += "매수" in act
                n_sell += "매도" in act
                if cols[7].button("🗒️ 등록", key=f"v9_act_reg_{j}",
                                  help="이 액션을 액션아이템으로 등록"):
                    items = AI.load_items()
                    AI.add_item(items, f"액션추천:{date.today().isoformat()}", "리밸런싱",
                                f"{p['name']} {act.replace('🔻 ', '').replace('🔺 ', '')} "
                                f"₩{r['amt_krw']:,.0f} — {r['strat'].split(' ', 1)[-1]} 시그널({sig['label']})",
                                detail=f"목표비중 {sig['target']:.0%} vs 실제 {r['cur_ratio']:.0%} · "
                                       f"{p['account']} · {p['_ticker']}")
                    AI.save_items(items)
                    GDRIVE.autopush_toast("action_items.csv")
                    st.toast(f"액션아이템 등록: {p['name']} {act}")
            else:
                cols[7].write("")
        st.caption(f"요약: 🔺매수 {n_buy}종목 · 🔻매도 {n_sell}종목 · 🟰보유 {len(results)-n_buy-n_sell}종목")

    # ── §14 종목 주가 트렌드 + 실매매·시그널 마커 (전역 필터와 동기화) ──
    st.divider()
    st.markdown("##### 📉 주가 트렌드 — 실제 매매 기록 + 전략 시그널")
    # 종목 목록은 사이드바 자산군·종목 필터를 반영, 기간도 사이드바 '기간'과 연동
    chart_opts = {p["_label"]: p for p in tradable if p["asset_id"] in ctx.sel_assets}
    if not chart_opts:
        st.info("선택된 자산군·종목 중 실시간 시세가 있는 종목이 없습니다(사이드바 필터 확인).")
        return
    sc1, sc2 = st.columns([3, 2])
    sel = sc1.selectbox("종목 (사이드바 필터 반영)", list(chart_opts.keys()), key="v9_act_chart_sel")
    p = chart_opts[sel]
    default_strat = strat_defaults.get(p["asset_id"]) or strat_names[0]
    chart_strat = sc2.selectbox("표시할 전략 시그널", strat_names,
                                index=strat_names.index(default_strat) if default_strat in strat_names else 0,
                                key="v9_act_chart_strat")
    since = ctx.basis_date
    yrs = max(1, int(((date.today() - since).days / 365.25) + 0.999))
    st.caption(f"기간: {ctx.basis_label} ({since.isoformat()}) ~ 오늘 — 사이드바 '기간'과 연동됩니다.")

    sig = latest_signal(p["_ticker"], v6.STRATS[chart_strat], years=yrs)
    if sig is None:
        st.error("시세 데이터를 가져오지 못했습니다.")
        return
    df = sig["df"]
    df = df[df["date"] >= pd.Timestamp(since)]
    if df.empty:
        st.warning("선택한 기간에 해당하는 시세가 없습니다.")
        return

    fig = go.Figure()
    # 전략 목표비중 배경 음영 (우측 축)
    fig.add_trace(go.Scatter(x=df["date"], y=df["target"] * 100, name="전략 목표비중(%)",
                             mode="lines", line=dict(color="#94a3b8", width=1),
                             fill="tozeroy", fillcolor="rgba(148,163,184,0.15)", yaxis="y2"))
    fig.add_trace(go.Scatter(x=df["date"], y=df["price"], name="주가",
                             mode="lines", line=dict(color="#2980b9", width=2)))
    # 전략 시그널 이벤트 마커
    ev = df[df["rule"] != ""] if "rule" in df.columns else pd.DataFrame()
    if not ev.empty:
        fig.add_trace(go.Scatter(
            x=ev["date"], y=ev["price"], mode="markers", name="전략 시그널",
            marker=dict(symbol="diamond", size=8, color="#7c3aed",
                        line=dict(color="#4c1d95", width=1)),
            hovertext=[f"{pd.Timestamp(d).strftime('%Y-%m-%d')} {r} → 목표 {t:.0%}"
                       for d, r, t in zip(ev["date"], ev["rule"], ev["target"])],
            hoverinfo="text"))
    # 실제 매매 마커 (같은 티커의 원장 거래 — 전 계좌, 선택 소유자)
    aids = {q["asset_id"] for q in ctx.pos if prices.ticker_of(q.get("price_source")) == p["_ticker"]}
    d0 = pd.Timestamp(df["date"].iloc[0])
    buys, sells = [], []
    for t in ctx.L.txns:
        if t["owner"] not in ctx.owner_set or t["asset_id"] not in aids:
            continue
        typ = norm_type(t["type"])
        if typ not in ("BUY", "SELL"):
            continue
        try:
            ts = pd.Timestamp(str(t["date"]))
            px = float(t.get("price") or 0)
        except (ValueError, TypeError):
            continue
        if ts < d0:
            continue
        if not px:   # 단가 미기록 시 그 날짜 시세로 근사
            near = df[df["date"] <= ts]
            px = float(near["price"].iloc[-1]) if not near.empty else None
        if px is None:
            continue
        note = (t.get("note") or "").strip()
        hover = f"{t['date']} {'매수' if typ == 'BUY' else '매도'} {t.get('qty') or ''}주 @ {px:,.2f}"
        if note:
            hover += f"<br>💬 {note[:120]}"
        (buys if typ == "BUY" else sells).append((ts, px, hover))
    for pts, name, sym, color in ((buys, "실제 매수", "triangle-up", "#16a34a"),
                                  (sells, "실제 매도", "triangle-down", "#dc2626")):
        if pts:
            fig.add_trace(go.Scatter(
                x=[x for x, _, _ in pts], y=[y for _, y, _ in pts], mode="markers", name=name,
                marker=dict(symbol=sym, size=12, color=color, line=dict(color="#111827", width=1)),
                hovertext=[h for _, _, h in pts], hoverinfo="text"))

    # 나의 평단가(실제·계좌 통합) — 눈에 잘 띄는 굵은 실선
    if aids:
        dates_str = [pd.Timestamp(d).strftime("%Y-%m-%d") for d in df["date"]]
        avg_real = [a for _, a in shared.real_avg_cost_series(ctx.L, ctx.owner_set,
                                                              sorted(aids)[0], dates_str)]
        fig.add_trace(go.Scatter(x=df["date"], y=avg_real, name="나의 평단가",
                                 mode="lines", line=dict(color="#16a34a", width=3),
                                 connectgaps=True,
                                 hovertemplate="나의 평단가 %{y:,.2f}<extra></extra>"))

    _, _, cur = v6.market_of(p["_ticker"])
    fig.update_layout(
        height=460, margin=dict(l=10, r=10, t=40, b=10),
        title=f"{p['name']} ({p['_ticker']}) — 주가 + 실제매매(▲▼) + {chart_strat.split(' ', 1)[-1]} 시그널(◆)",
        yaxis_title=f"주가({cur})",
        yaxis2=dict(title="목표비중(%)", overlaying="y", side="right", range=[0, 105], showgrid=False),
        legend=dict(orientation="h", y=-0.2))
    st.plotly_chart(fig, width="stretch", key="v9_act_chart")
    st.caption("▲녹=실제 매수 · ▼빨=실제 매도(hover에 수량·단가·thesis) · ◆보라=전략 시그널(hover에 룰·목표비중) · "
               "회색 음영=전략 목표비중(우측 축). 현재 국면: " + sig["label"])
