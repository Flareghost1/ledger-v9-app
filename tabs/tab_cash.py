# -*- coding: utf-8 -*-
"""💵 현금흐름 (v9 §18·19: 예상 스케줄에 실제 수령액 병기 + 월 막대 클릭 시 구성 항목 표시)"""
from datetime import date

import pandas as pd
import streamlit as st
import plotly.graph_objects as go

import cashflow

MONTHS = [f"{i}월" for i in range(1, 13)]


def _actual_monthly(ctx, year):
    """원장 실수령(DIVIDEND/INTEREST/COUPON) 월별 합계 + 항목 리스트. 전역 필터(소유자·종목) 반영."""
    monthly = [0.0] * 12
    detail = [[] for _ in range(12)]
    for i in ctx.L.income:
        if i["owner"] not in ctx.owner_set:
            continue
        if ctx.asset_filter_on and i["asset_id"] not in ctx.sel_assets:
            continue
        d = str(i["date"])
        if d[:4] != str(year):
            continue
        try:
            m = int(d[5:7])
        except ValueError:
            continue
        monthly[m - 1] += i["amount_krw"]
        detail[m - 1].append(i)
    return monthly, detail


def render(ctx):
    year = date.today().year
    cf = cashflow.project(ctx.pos_f, ctx.fx, lambda p: p["_v"])
    actual, actual_detail = _actual_monthly(ctx, year)

    m = st.columns(4)
    m[0].metric("연 세전(예상)", f"₩{cf['annual_gross']:,.0f}")
    m[1].metric("연 세후(예상)", f"₩{cf['annual_net']:,.0f}")
    m[2].metric("월평균(세후)", f"₩{cf['annual_net']/12:,.0f}")
    m[3].metric(f"{year} 실제 수령 누계", f"₩{sum(actual):,.0f}",
                f"예상 YTD ₩{sum(cf['monthly'][:date.today().month]):,.0f} 대비", delta_color="off")

    # §18: 예상(스케줄) vs 실제 수령 그룹 막대 + §19: 클릭 시 그 달 구성
    fig = go.Figure()
    fig.add_trace(go.Bar(x=MONTHS, y=list(cf["monthly"]), name="예상(배당스케줄)",
                         marker_color="#94a3b8",
                         text=[f"{v/1e4:,.0f}만" if v else "" for v in cf["monthly"]], textposition="outside"))
    fig.add_trace(go.Bar(x=MONTHS, y=actual, name=f"실제 수령({year})", marker_color="#2980b9",
                         text=[f"{v/1e4:,.0f}만" if v else "" for v in actual], textposition="outside"))
    fig.update_layout(barmode="group", height=360, margin=dict(l=10, r=10, t=40, b=10),
                      title="월별 현금흐름 — 예상 vs 실제 (세전 · 막대를 클릭하면 그 달 구성 항목 표시)",
                      legend=dict(orientation="h", y=-0.2), clickmode="event+select")
    ev = st.plotly_chart(fig, width="stretch", on_select="rerun",
                         selection_mode="points", key="v9_cf_chart")

    sel_month = None
    pts = (ev or {}).get("selection", {}).get("points", [])
    for pt in pts:
        if pt.get("x") in MONTHS:
            sel_month = MONTHS.index(pt["x"])
        elif "point_index" in pt:
            sel_month = pt["point_index"]
    # §15: 예상과 실제를 한 테이블로 합치고, 자산군 열 추가 · '비과세' 대신 '세금' 종류 표시
    cls_of = {p["asset_id"]: (p["asset_class"] or "기타") for p in ctx.pos}
    name_of = {p["asset_id"]: p["name"] for p in ctx.pos}

    def _tax_kind(asset_id, tax_exempt):
        if tax_exempt:
            return "🟢 비과세"
        cls = cls_of.get(asset_id, "")
        if cls in ("BOND_KR", "BOND_FX"):
            return "🔵 이자소득 15.4%"
        return "🔵 배당소득 15.4%"

    if sel_month is not None:
        st.markdown(f"##### 🔍 {sel_month+1}월 구성 항목 (예상 vs 실제)")
        merged = {}
        for r in cf["rows"]:
            if r["months"] and (sel_month + 1) in r["months"]:
                aid = r["asset_id"]
                merged.setdefault(aid, dict(자산군=cls_of.get(aid, "기타"),
                                            항목=name_of.get(aid, r["label"]),
                                            예상=0.0, 실제=0.0,
                                            세금=_tax_kind(aid, r["tax_exempt"]), 근거=r["basis"]))
                merged[aid]["예상"] += r["annual"] / len(r["months"])
        for i in actual_detail[sel_month]:
            aid = i["asset_id"]
            merged.setdefault(aid, dict(자산군=cls_of.get(aid, "기타"),
                                        항목=name_of.get(aid, aid),
                                        예상=0.0, 실제=0.0,
                                        세금=_tax_kind(aid, i["tax_exempt"]), 근거="원장 실수령"))
            merged[aid]["실제"] += i["amount_krw"]
        if merged:
            mdf = pd.DataFrame(list(merged.values()))
            mdf["차이"] = mdf["실제"] - mdf["예상"]
            mdf = mdf.sort_values("예상", ascending=False)
            st.dataframe(mdf, width="stretch", hide_index=True,
                         column_order=("자산군", "항목", "예상", "실제", "차이", "세금", "근거"),
                         column_config={
                             "예상": st.column_config.NumberColumn(format="₩%,.0f"),
                             "실제": st.column_config.NumberColumn(format="₩%,.0f"),
                             "차이": st.column_config.NumberColumn(format="₩%,.0f"),
                         })
            st.caption(f"예상 합계 ₩{mdf['예상'].sum():,.0f} · 실제 합계 ₩{mdf['실제'].sum():,.0f}")
        else:
            st.caption("이 달 예정·수령 항목이 없습니다.")
    else:
        st.caption("💡 월 막대를 클릭하면 그 달에 어떤 종목에서 얼마가 들어오는지(예상·실제) 표시됩니다.")

    st.markdown("##### 📋 연간 구성 항목")
    rows = [dict(자산군=cls_of.get(r["asset_id"], "기타"),
                 항목=name_of.get(r["asset_id"], r["label"]),
                 연현금흐름=float(r["annual"]),
                 지급월=",".join(f"{mm}월" for mm in r["months"]) if r["months"] else "만기/일시",
                 세금=_tax_kind(r["asset_id"], r["tax_exempt"]),
                 근거=r["basis"]) for r in cf["rows"]]
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True, column_config={
        "연현금흐름": st.column_config.NumberColumn(format="₩%,.0f"),
    })
    st.caption(f"예상 = 배당스케줄(INCOME_TABLE) 이론치 · 실제 = 원장 DIVIDEND/INTEREST/COUPON 실수령({ctx.owner_label}). "
               "일시성(ELB 등) ₩{:,.0f}는 월 배분 없이 별도.".format(cf["lump"]))
