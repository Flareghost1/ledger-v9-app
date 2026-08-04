# -*- coding: utf-8 -*-
"""📊 현황 — 총자산 요약 + 자산군 파이 + 보유 포지션 + 신한 [1721] 스타일 수익률 화면 (v9 §4)"""
from datetime import date

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import snapshots as SNAP
from ledger import adjust_position, set_manual_price
import gdrive_sync as GDRIVE
from tabs import shared


def render(ctx):
    # ── 상단 비교 메트릭 (비교기준은 사이드바 전역 필터) ──
    if ctx.basis == "직접입력":
        cmp_ = SNAP.compare_asof(ctx.snap_key, ctx.basis_date.isoformat(), ctx.total)
    else:
        cmp_ = SNAP.compare(ctx.snap_key, ctx.basis, ctx.total)
    if cmp_:
        approx = f" ·근사({cmp_['base_date']})" if cmp_["approx"] else ""
        delta_txt = f"{cmp_['diff']:+,.0f}원 ({cmp_['pct']:+.1%}) {ctx.basis_label}대비{approx}"
    else:
        delta_txt = None
        st.caption(f"'{ctx.basis_label}' 시점 스냅샷이 아직 없습니다. 매일 앱을 열면 자동으로 쌓입니다.")

    def _cmp_delta(basis_key):
        c = SNAP.compare(ctx.snap_key, basis_key, ctx.total)
        return f"{c['diff']:+,.0f}원 ({c['pct']:+.1%})" if c else None

    c1, c2, c3, c4 = st.columns(4)
    c1.metric(f"{ctx.owner_label} 총자산", f"₩{ctx.total:,.0f}", delta_txt)
    c2.metric("전일 대비", "총자산", _cmp_delta("전일"))
    c3.metric("전주 대비", "총자산", _cmp_delta("전주"))
    unreal = sum(p["_pnl"] for p in ctx.pos if p["_live"])
    c4.metric("미실현손익(실시간종목)", f"₩{unreal:,.0f}")
    d1, d2 = st.columns(2)
    d1.metric("주식·자산 평가액", f"₩{ctx.total_eq:,.0f}")
    d2.metric("현금 잔고", f"₩{ctx.cash_krw:,.0f}")

    filt_on = ctx.filter_on
    filt_txt = ""
    if ctx.class_filter_on:
        filt_txt += " · 자산군: " + ", ".join(sorted(ctx.sel_classes))
    if ctx.asset_filter_on:
        filt_txt += f" · 종목 {len(ctx.sel_assets)}개 선택"

    left, right = st.columns([1, 1.5])
    with left:
        # 선택된 자산군·종목만 반영(사이드바 전역 필터와 동기화).
        # 조각 클릭 선택 기능은 제거 — 필터는 사이드바로 일원화(§4).
        by_class_f = ctx.by_class_f
        if by_class_f:
            fig = go.Figure(data=[go.Pie(labels=list(by_class_f.keys()),
                                         values=list(by_class_f.values()), hole=0.4)])
            fig.update_layout(height=380, margin=dict(l=10, r=10, t=30, b=10),
                              title="자산군별 비중 (선택 항목 기준)")
            fig.update_traces(hovertemplate="%{label}<br>₩%{value:,.0f} (%{percent})<extra></extra>")
            st.plotly_chart(fig, width="stretch", key="v9_pie")
        else:
            st.info("선택된 자산군·종목이 없습니다. 사이드바에서 선택하세요.")
        # §4: 선택한 자산군/종목의 합계 자산금액
        pct_of_total = (ctx.total_f / ctx.total * 100) if ctx.total else 0
        st.metric("선택 항목 합계", f"₩{ctx.total_f:,.0f}",
                  f"전체 대비 {pct_of_total:.1f}%" + (" · 전체 선택됨" if not filt_on else ""),
                  delta_color="off")
        st.caption(f"주식·자산 ₩{ctx.total_eq_f:,.0f} + 현금 ₩{ctx.cash_krw_f:,.0f}")
        if filt_on:
            st.caption("사이드바 필터 적용 중" + filt_txt)
    with right:
        # 현금도 CASH 자산군으로 포지션 표에 포함
        cash_pos = []
        for c in ctx.cash_rows_f:
            krw = c["amount"] * (ctx.fx if c["ccy"] == "USD" else 1)
            cash_pos.append(dict(owner=c["owner"], account=c["account"], asset_id=f"CASH.{c['ccy']}",
                                 name=f"현금 ({c['ccy']})", asset_class="CASH", qty=c["amount"],
                                 avg_cost=None, cost_krw=krw, ccy=c["ccy"], _v=krw, _cp=None,
                                 _live=False, revalue_price=None, _is_cash=True))
        shown = ctx.pos_f + cash_pos
        title = "보유 포지션 (실시간 평가 · 현금 포함)"
        if filt_on:
            title += f" — 필터 적용 ({len(shown)}건)"
        st.markdown(f"#### {title}")

        def _price_status(p):
            if p.get("_is_cash"):
                return "💵 현금"
            if p["_live"]:
                return "🟢 실시간"
            if p.get("revalue_price") is not None:
                return "🔄 수동갱신"
            return "⚪ 미갱신(원가)"

        def _entry_fx(p):
            # 매입 시점 로트들의 가중평균 환율 — 원화환산 취득원가 ÷ 외화 취득원가.
            # 수익률(_v/cost_krw-1)이 시세만이 아니라 이 환율까지 반영한 결과라는 걸
            # 바로 옆에서 확인할 수 있게 한다(자산군·종목 필터로 숨기지 않고 항상 계산).
            if p.get("_is_cash") or p.get("ccy") == "KRW" or not p.get("qty") or not p.get("avg_cost"):
                return np.nan
            return p["cost_krw"] / (p["qty"] * p["avg_cost"])

        def _cur_fx(p):
            if p.get("_is_cash") or p.get("ccy") == "KRW":
                return np.nan
            if p.get("ccy") == "USD":
                return ctx.fx
            return np.nan   # USD 외 통화의 실시간 환율은 💱 환율차트 탭에서 확인

        vdf = pd.DataFrame([dict(
            종목=p["name"], 계좌=p["account"], 자산군=p["asset_class"],
            수량=p["qty"],
            평단=(p["avg_cost"] if p.get("avg_cost") is not None else np.nan),
            현재가=(p["_cp"] if p["_cp"] is not None else np.nan),
            평가액=float(p["_v"]),
            수익률=(np.nan if (p.get("_is_cash") or not p["cost_krw"]) else (p["_v"] / p["cost_krw"] - 1) * 100),
            매입환율=_entry_fx(p),
            현재환율=_cur_fx(p),
            가격상태=_price_status(p),
            갱신일=(p.get("revalue_date") or "-") if not p.get("_is_cash") and not p["_live"] else "-",
        ) for p in shown]) if shown else pd.DataFrame()

        if vdf.empty:
            st.info("선택된 항목이 없습니다.")
        else:
            # 정렬은 헤더 클릭(클라이언트) 대신 여기서 pandas로 처리한다.
            # Styler로 색을 입히면 클라이언트 정렬 시 색이 원래 행 위치에 남아 어긋나기 때문에,
            # '정렬을 먼저 하고 그 결과에 색을 입히는' 순서로 두 기능을 동시에 살린다.
            sc1, sc2 = st.columns([2, 1])
            sort_col = sc1.selectbox("정렬 기준", ["평가액", "수익률", "종목", "자산군", "계좌",
                                                   "수량", "평단", "현재가", "매입환율"], key="v9_pos_sort")
            asc = sc2.radio("정렬", ["내림차순", "오름차순"], horizontal=True,
                            key="v9_pos_sort_dir") == "오름차순"
            vdf = vdf.sort_values(sort_col, ascending=asc, na_position="last").reset_index(drop=True)

            def _ret_color(v):
                if v is None or (isinstance(v, float) and np.isnan(v)):
                    return ""
                if v > 0:
                    return "color:#dc2626;font-weight:600"    # 국내 관행: 상승=빨강
                if v < 0:
                    return "color:#2563eb;font-weight:600"    # 하락=파랑
                return ""

            sty = (vdf.style
                   .format({"수량": "{:,.4f}", "평단": "{:,.2f}", "현재가": "{:,.2f}",
                            "평가액": "₩{:,.0f}", "수익률": "{:+.1f}%",
                            "매입환율": "{:,.2f}", "현재환율": "{:,.2f}"}, na_rep="-")
                   .map(_ret_color, subset=["수익률"]))
            st.dataframe(sty, width="stretch", hide_index=True, height=420,
                         column_order=("종목", "계좌", "자산군", "수량", "평단", "현재가",
                                       "평가액", "수익률", "매입환율", "현재환율", "가격상태", "갱신일"))
            st.caption("정렬은 위 '정렬 기준'에서 바꾸세요(헤더 클릭 대신 — 색상 정확도 유지). "
                       "수익률 🔴상승/🔵하락 · 🟢 실시간 · 🔄 수동갱신 · ⚪ 미갱신(원가) · 💵 현금 · "
                       "갱신일은 🔄 수동갱신 종목에만 표시됩니다. **수익률은 시세 변동 + 환율 변동을 함께 반영**한 값이라, "
                       "매입환율(매수 시점 가중평균)과 현재환율을 나란히 두어 그 차이가 수익률에 얼마나 영향줬는지 "
                       "바로 확인할 수 있게 했습니다(외화 자산만 해당, USD 외 통화의 현재환율은 💱 환율차트 탭 참고).")
        n_stale = sum(1 for p in shown
                      if not p.get("_is_cash") and not p["_live"] and p.get("revalue_price") is None)
        if n_stale:
            st.caption(f"⚪ 미갱신 {n_stale}건 — 취득원가를 평가액으로 대신 표시 중. "
                       "실제 현재가를 알려주시면 REVALUE 거래로 갱신해드립니다.")

        with st.expander("✏️ 수량·평단 직접 보정 (원장에 반영)"):
            st.caption("잘못된 수량·평단을 고친 뒤 '원장에 반영'을 누르면 보정 거래(TRANSFER_OUT/IN, tag=ADJUST)로 "
                       "자동 기록됩니다. 평가액은 시세×환율 자동계산이라 대상 아님.")
            editable = [p for p in sorted(shown, key=lambda x: -x["_v"]) if not p.get("_is_cash")]

            def _pos_key(p):
                return f"{p['owner']}|{p['account']}|{p['asset_id']}"

            edit_src = pd.DataFrame([dict(
                _key=_pos_key(p), 종목=p["name"], 계좌=p["account"],
                수량=round(p["qty"], 4), 평단=round(p["avg_cost"], 4),
            ) for p in editable])
            edited_pos = st.data_editor(
                edit_src,
                column_order=("종목", "계좌", "수량", "평단"),
                column_config={
                    "종목": st.column_config.TextColumn(disabled=True),
                    "계좌": st.column_config.TextColumn(disabled=True),
                    "수량": st.column_config.NumberColumn(format="%.4f"),
                    "평단": st.column_config.NumberColumn(format="%.4f"),
                },
                hide_index=True, width="stretch", height=320, key="v9_pos_editor")

            pmap = {_pos_key(p): p for p in editable}
            diffs = []
            for _, r in edited_pos.iterrows():
                p = pmap.get(r["_key"])
                if not p:
                    continue
                base_qty, base_avg = round(p["qty"], 4), round(p["avg_cost"], 4)
                if abs(round(float(r["수량"]), 4) - base_qty) > 1e-6 or abs(round(float(r["평단"]), 4) - base_avg) > 1e-6:
                    diffs.append((p, float(r["수량"]), float(r["평단"])))
            if diffs:
                st.warning(f"⚠️ {len(diffs)}건 변경 감지 — 아직 원장에 반영되지 않았습니다.")
                for p, nq, na in diffs:
                    st.caption(f"· {p['name']}({p['account']}): 수량 {p['qty']:,.4f} → {nq:,.4f} · "
                               f"평단 {p['avg_cost']:,.4f} → {na:,.4f}")
                if st.button("🔒 변경사항 원장에 반영", type="primary", key="v9_pos_adjust_apply"):
                    for p, nq, na in diffs:
                        adjust_position(p, nq, na)
                    GDRIVE.autopush_toast("transactions.csv")
                    st.cache_data.clear()
                    st.success(f"{len(diffs)}건 보정 완료 — 원장에 기록되었습니다.")
                    st.rerun()

        with st.expander("🔄 현재가 직접 갱신 (실시간 시세 없는 종목)"):
            st.caption("자동 시세 조회가 안 되는 종목(펀드·ELS·채권 등)의 현재가를 직접 입력합니다. "
                       "REVALUE 거래로 원장에 기록되며, 취득원가(수익률 계산의 분모)는 바뀌지 않습니다. "
                       "입력 형식은 위 표의 '현재가' 칸과 동일한 숫자입니다(예: 펀드/ELS는 총평가금액, "
                       "채권은 액면 10,000당 단가 비율).")
            revalable = [p for p in sorted(shown, key=lambda x: -x["_v"])
                         if not p.get("_is_cash") and not p["_live"]]
            if not revalable:
                st.caption("실시간 시세가 없는 종목이 없습니다 — 모두 자동 갱신 중입니다.")
            else:
                def _rv_key(p):
                    return f"{p['owner']}|{p['account']}|{p['asset_id']}"

                rv_src = pd.DataFrame([dict(
                    _key=_rv_key(p), 종목=p["name"], 계좌=p["account"], 수량=round(p["qty"], 4),
                    현재가=round(p["revalue_price"], 4) if p.get("revalue_price") is not None else round(p["avg_cost"], 4),
                    마지막갱신일=p.get("revalue_date") or "미갱신(원가 표시중)",
                ) for p in revalable])
                edited_rv = st.data_editor(
                    rv_src,
                    column_order=("종목", "계좌", "수량", "현재가", "마지막갱신일"),
                    column_config={
                        "종목": st.column_config.TextColumn(disabled=True),
                        "계좌": st.column_config.TextColumn(disabled=True),
                        "수량": st.column_config.NumberColumn(format="%.4f", disabled=True),
                        "현재가": st.column_config.NumberColumn(format="%.4f"),
                        "마지막갱신일": st.column_config.TextColumn(disabled=True),
                    },
                    hide_index=True, width="stretch", height=min(320, 60 + 36 * len(revalable)), key="v9_rv_editor")

                rvmap = {_rv_key(p): p for p in revalable}
                rv_diffs = []
                for _, r in edited_rv.iterrows():
                    p = rvmap.get(r["_key"])
                    if not p:
                        continue
                    base = round(p["revalue_price"], 4) if p.get("revalue_price") is not None else round(p["avg_cost"], 4)
                    if abs(float(r["현재가"]) - base) > 1e-6:
                        rv_diffs.append((p, float(r["현재가"])))
                if rv_diffs:
                    st.warning(f"⚠️ {len(rv_diffs)}건 변경 감지 — 아직 원장에 반영되지 않았습니다.")
                    today_txt = date.today().isoformat()
                    for p, new_price in rv_diffs:
                        old = p.get("revalue_price") if p.get("revalue_price") is not None else p["avg_cost"]
                        st.caption(f"· {p['name']}({p['account']}): 현재가 {old:,.4f} → {new_price:,.4f} "
                                   f"(갱신일 {today_txt}로 기록)")
                    if st.button("🔒 변경사항 원장에 반영", type="primary", key="v9_rv_apply"):
                        for p, new_price in rv_diffs:
                            set_manual_price(p, new_price)
                        GDRIVE.autopush_toast("transactions.csv")
                        st.cache_data.clear()
                        st.success(f"{len(rv_diffs)}건 현재가 갱신 완료 — 갱신일 {today_txt}로 기록되었습니다.")
                        st.rerun()

    # ── §4: 신한 [1721] 종합계좌 수익률(기간) 스타일 ──
    st.divider()
    st.markdown(f"#### 📈 기간 수익률 현황 — {ctx.basis_label} ~ 오늘 (신한 [1721] 스타일)")
    shared.render_perf(ctx, key="v9_status_perf")
