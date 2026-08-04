# -*- coding: utf-8 -*-
"""📒 매매일지 (v9 §5~9 + 후속 스프린트)
- 전역 필터(소유자·기간·자산군·종목) 반영, '본인만 보기' 삭제(§5·7)
- 매매 + 소득기록(DIVIDEND/INTEREST/COUPON) 이벤트 통합(§6)
- 이벤트 일련번호(§8) + 신한 스타일 그래프에 번호 마커(§9)
- 같은 종목·다른 계좌는 하나로 합쳐서 표시(후속 §4)
- 신규: 주가 트렌드 + 나의 평단가(계좌 통합) + 실제 매매 마커(후속 §5)
- 표 정렬은 column_config 기반 숫자 컬럼으로(후속 §1 — Styler는 정렬 후 색이 어긋나는 문제가 있음)
"""
from datetime import date, timedelta

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import prices
from enums import norm_type
from tabs import shared

EVENT_TYPES = {"BUY": "🔺매수", "SELL": "🔻매도",
               "DIVIDEND": "💵배당", "INTEREST": "💵이자", "COUPON": "💵쿠폰"}


def _events(ctx):
    """전역 필터 반영 이벤트 목록. 같은 날짜·유형·종목이 여러 계좌에 걸쳐 있으면 한 줄로 합산
    (수량·금액 합산, 단가는 수량가중평균, 계좌는 콤마 나열) — 종목 기준으로 보기 위함."""
    since = ctx.basis_date.isoformat()
    raw = []
    for t in ctx.L.txns:
        if t["owner"] not in ctx.owner_set:
            continue
        typ = norm_type(t["type"])
        if typ not in EVENT_TYPES:
            continue
        d = str(t["date"])
        if d < since:
            continue
        aid = t["asset_id"]
        meta = ctx.L.assets.get(aid, {})
        cls = t.get("asset_class") or meta.get("asset_class") or "기타"
        if ctx.class_filter_on and cls not in ctx.sel_classes:
            continue
        if ctx.asset_filter_on and aid not in ctx.sel_assets:
            continue
        krw = shared._txn_krw(t)
        try:
            qty = float(t.get("qty") or 0)
        except (ValueError, TypeError):
            qty = 0.0
        try:
            price = float(t.get("price") or 0)
        except (ValueError, TypeError):
            price = 0.0
        raw.append(dict(date=d, txn_id=t.get("txn_id", ""), owner=t["owner"], account=t["account"],
                        asset_id=aid, name=meta.get("name_kr", aid), type=typ, asset_class=cls,
                        type_ko=EVENT_TYPES[typ], qty=qty, price=price,
                        krw=krw, tag=t.get("tag", ""), note=t.get("note", "")))

    merged = {}
    order = []
    for e in raw:
        key = (e["date"], e["type"], e["asset_id"])
        if key not in merged:
            merged[key] = dict(e, accounts={e["account"]}, notes=[n for n in [e["note"]] if n])
            order.append(key)
        else:
            m = merged[key]
            m["qty"] += e["qty"]
            m["krw"] += e["krw"]
            m["accounts"].add(e["account"])
            if e["note"]:
                m["notes"].append(e["note"])
    out = []
    for key in order:
        m = merged[key]
        m["account"] = ", ".join(sorted(m["accounts"]))
        m["note"] = " · ".join(m["notes"][:2]) + (" …" if len(m["notes"]) > 2 else "")
        out.append(m)
    out.sort(key=lambda e: (e["date"], e["asset_id"]))
    for i, e in enumerate(out, 1):
        e["no"] = i
    return out


def _price_trend_section(ctx):
    st.markdown("#### 📉 주가 트렌드 — 실제 종가 + 나의 평단가 (계좌 통합)")
    # 전역 자산군·종목 필터와 동기화 — 선택된 것 중 실시간 시세가 있는 종목만 목록에 올린다.
    asset_opts = {p["name"]: p["asset_id"] for p in ctx.pos_f if p["_live"]}
    if not asset_opts:
        st.info("선택된 자산군·종목 중 실시간 시세가 있는 종목이 없습니다(사이드바 필터 확인).")
        return
    sel_name = st.selectbox("종목 (사이드바 필터 반영)", list(asset_opts.keys()),
                            key="v9_journal_trend_sel")
    aid = asset_opts[sel_name]
    p_ref = next(p for p in ctx.pos_f if p["asset_id"] == aid)
    tk = prices.ticker_of(p_ref["price_source"])

    # 기간도 전역 설정(사이드바 '기간')과 연동 — 그 시작일이 포함되도록 조회 연수를 잡는다.
    since = ctx.basis_date
    yrs = max(1, int(((date.today() - since).days / 365.25) + 0.999))
    hist = prices.history(tk, years=yrs)
    if hist is None or hist.empty:
        st.warning("시세 데이터를 가져오지 못했습니다.")
        return
    hist = hist[hist["date"] >= pd.Timestamp(since)]
    if hist.empty:
        st.warning("선택한 기간에 해당하는 시세가 없습니다.")
        return
    st.caption(f"기간: {ctx.basis_label} ({since.isoformat()}) ~ 오늘 — 사이드바 '기간'과 연동됩니다.")

    dates_str = [d.strftime("%Y-%m-%d") for d in hist["date"]]
    series = shared.real_avg_cost_series(ctx.L, ctx.owner_set, aid, dates_str)
    avg_line = [a for _, a in series]

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=hist["date"], y=hist["price"], name="종가",
                             mode="lines", line=dict(color="#2980b9", width=2)))
    fig.add_trace(go.Scatter(x=hist["date"], y=avg_line, name="나의 평단가(계좌 통합)",
                             mode="lines", line=dict(color="#c0392b", width=2, dash="dot"),
                             connectgaps=True))

    buys, sells = [], []
    for t in ctx.L.txns:
        if t["owner"] not in ctx.owner_set or t["asset_id"] != aid:
            continue
        typ = norm_type(t["type"])
        if typ not in ("BUY", "SELL"):
            continue
        d = str(t["date"])
        if d < dates_str[0]:
            continue
        try:
            px = float(t.get("price") or 0)
        except (ValueError, TypeError):
            px = 0
        if not px:
            near = hist[hist["date"] <= pd.Timestamp(d)]
            px = float(near["price"].iloc[-1]) if not near.empty else None
        if px is None:
            continue
        note = (t.get("note") or "").strip()
        hover = f"{d} {'매수' if typ == 'BUY' else '매도'} {t.get('account','')} {t.get('qty') or ''}주 @ {px:,.2f}"
        if note:
            hover += f"<br>💬 {note[:100]}"
        (buys if typ == "BUY" else sells).append((pd.Timestamp(d), px, hover))
    for pts, name, sym, color in ((buys, "실제 매수", "triangle-up", "#16a34a"),
                                  (sells, "실제 매도", "triangle-down", "#dc2626")):
        if pts:
            fig.add_trace(go.Scatter(x=[x for x, _, _ in pts], y=[y for _, y, _ in pts],
                                     mode="markers", name=name,
                                     marker=dict(symbol=sym, size=11, color=color,
                                                 line=dict(color="#111827", width=1)),
                                     hovertext=[h for _, _, h in pts], hoverinfo="text"))
    cur = "$" if p_ref["ccy"] == "USD" else "₩"
    fig.update_layout(height=420, margin=dict(l=10, r=10, t=30, b=10),
                      title=f"{sel_name} — 종가 vs 나의 평단가(점선) · ▲매수 ▼매도(계좌 통합)",
                      yaxis_title=f"가격({cur})", legend=dict(orientation="h", y=-0.2))
    st.plotly_chart(fig, width="stretch", key="v9_journal_trend_chart")
    st.caption("나의 평단가는 여러 계좌에 나뉜 보유분을 전부 합쳐 이동평균법으로 계산합니다("
               "매도는 평단에 영향 없이 수량만 줄임). 매수/매도 마커도 계좌 구분 없이 종목 기준입니다.")


def render(ctx):
    st.markdown("#### 📒 매매일지 — 매매 + 소득 이벤트")
    st.caption(f"전역 필터 적용: {ctx.owner_label} · {ctx.basis_label}~오늘"
               + (" · 자산군 필터" if ctx.class_filter_on else "")
               + (" · 종목 필터" if ctx.asset_filter_on else "")
               + " — 사이드바에서 변경. 같은 종목이 여러 계좌에 있으면 한 줄로 합쳐서 표시합니다.")
    evs = _events(ctx)

    # §9: 총자산/손익/수익률 그래프 + 이벤트 번호 마커
    chart_events = [dict(no=e["no"], date=e["date"],
                         label=f"{e['type_ko']} {e['name']} {e['krw']:,.0f}원") for e in evs]
    shared.render_perf(ctx, key="v9_journal_perf", events=chart_events, show_table=False)

    if not evs:
        st.info("기간·필터 내 매매/소득 이벤트가 없습니다.")
    else:
        edf = pd.DataFrame([dict(번호=e["no"], 날짜=e["date"], 자산군=e["asset_class"], 계좌=e["account"],
                                 종목=f"{e['type_ko']} {e['name']}", 수량=e["qty"], 단가=e["price"],
                                 금액원화=e["krw"], 태그=e["tag"], 노트=e["note"]) for e in evs])
        edf = edf.sort_values("번호", ascending=False)
        st.dataframe(
            edf, width="stretch", hide_index=True, height=380,
            column_config={
                "번호": st.column_config.NumberColumn(width="small"),
                "수량": st.column_config.NumberColumn(format="%,.4f"),
                "단가": st.column_config.NumberColumn(format="%,.2f"),
                "금액원화": st.column_config.NumberColumn(format="₩%,.0f"),
            })
        st.caption(f"이벤트 {len(evs)}건 — 그래프의 주황 번호 마커와 표의 '번호'가 연결됩니다. "
                   "🔺매수 🔻매도 💵배당/이자/쿠폰 (컬럼 헤더 클릭 시 값 기준 정렬)")

    # 신규: 주가 트렌드 + 나의 평단가
    st.divider()
    _price_trend_section(ctx)

    # 실현손익 — 매도차익 + 현금소득(배당·이자·쿠폰)을 함께 본다(§9)
    st.divider()
    st.markdown("#### 💰 실현손익 (매도차익 + 현금소득)")
    since = ctx.basis_date.isoformat()

    def _in_scope(aid):
        return not ctx.asset_filter_on or aid in ctx.sel_assets

    rows = []
    for r in ctx.L.realized:
        if r["owner"] not in ctx.owner_set or str(r["date"]) < since or not _in_scope(r["asset_id"]):
            continue
        meta = ctx.L.assets.get(r["asset_id"], {})
        rows.append(dict(구분="🔻매도차익", 날짜=str(r["date"]), 종목=meta.get("name_kr", r["asset_id"]),
                         수량=r.get("qty"), 단가=r.get("price"), 평단=r.get("avg"),
                         금액원화=float(r["pnl_krw"]), 비고=r.get("note", "")))
    income_total = 0.0
    for i in ctx.L.income:
        if i["owner"] not in ctx.owner_set or str(i["date"]) < since or not _in_scope(i["asset_id"]):
            continue
        meta = ctx.L.assets.get(i["asset_id"], {})
        kind = {"DIVIDEND": "💵배당", "INTEREST": "💵이자", "COUPON": "💵쿠폰"}.get(i["type"], "💵소득")
        amt = float(i["amount_krw"])
        income_total += amt
        rows.append(dict(구분=kind, 날짜=str(i["date"]), 종목=meta.get("name_kr", i["asset_id"]),
                         수량=None, 단가=None, 평단=None, 금액원화=amt,
                         비고="비과세" if i.get("tax_exempt") else ""))

    if rows:
        rdf = pd.DataFrame(rows).sort_values("날짜", ascending=False)
        st.dataframe(rdf, width="stretch", hide_index=True, height=320, column_config={
            "수량": st.column_config.NumberColumn(format="%,.4f"),
            "단가": st.column_config.NumberColumn(format="%,.2f"),
            "평단": st.column_config.NumberColumn(format="%,.2f"),
            "금액원화": st.column_config.NumberColumn(format="₩%,.0f"),
        })
        sell_total = sum(r["금액원화"] for r in rows if r["구분"] == "🔻매도차익")
        m1, m2, m3 = st.columns(3)
        m1.metric("매도 실현손익", f"₩{sell_total:,.0f}")
        m2.metric("현금소득(배당·이자·쿠폰)", f"₩{income_total:,.0f}")
        m3.metric("합계", f"₩{sell_total + income_total:,.0f}")
    else:
        st.info("기간 내 매도·현금소득 기록이 없습니다.")

    with st.expander("🗂 전체 거래원장 보기 (소유자 필터만 적용)"):
        tdf = pd.DataFrame(ctx.L.txns)
        view = tdf[tdf["owner"].isin(ctx.owner_set)].sort_values(["date", "txn_id"], ascending=False)
        st.dataframe(view[["date", "owner", "account", "asset_id", "type", "qty", "price", "ccy", "tag", "note"]],
                     width="stretch", hide_index=True, height=360)
