# -*- coding: utf-8 -*-
"""🧾 세금리포트 (v9 §10: 전역 필터 중 '소유자만' 반영 — 기간 필터 무시, 해당 과세연도 기준)"""
from datetime import date

import pandas as pd
import streamlit as st

import tax_rules as tx


def render(ctx):
    today = date.today()
    L = ctx.L_tax           # 소유자 필터 반영 원장
    fin_full = ctx.fin_full
    taxsum = tx.summary(L, today)
    st.markdown("#### 🧾 세금 리포트")
    st.caption(f"소유자 필터({ctx.owner_label})만 반영합니다. 기간 필터는 무시 — 세금은 {today.year} 과세연도 기준.")
    gt = taxsum["gift_tax"]
    gt_pending = [r for r in gt if r["days_left"] >= 0]
    cc = st.columns(4)
    cg = taxsum["capgains"]
    cc[0].metric(f"해외양도세 예상({cg['year']})", f"₩{cg['tax']:,.0f}", f"실현손익 ₩{cg['realized_pnl']:,.0f}")
    cc[1].metric("금융소득 연말예상", f"₩{fin_full['est']['taxable']:,.0f}",
                 f"YTD ₩{fin_full['ytd']['taxable']:,.0f} ({fin_full['ratio']:.0%})", delta_color="inverse")
    cc[2].metric("이월과세 경고", f"{len(taxsum['carryover'])}건")
    cc[3].metric("증여세 신고 대기", f"{len(gt_pending)}건",
                 f"₩{sum(r['tax_due_net'] for r in gt_pending):,.0f}" if gt_pending else None)

    st.markdown("##### 📊 금융소득 종합 현황 (YTD 실현 + 연말 예상)")
    if fin_full["other_income_missing"]:
        st.warning(f"⚠️ {fin_full['year']}년 기타 종합소득(근로·사업·연금)이 미입력 상태(0원 처리)입니다. "
                   "⚙️ 설정 탭에서 입력하면 종합과세 세액이 정확해집니다.")
    _y, _e = fin_full["ytd"], fin_full["est"]
    fin_df = pd.DataFrame([
        dict(분류="🟢 비과세", YTD실현=_y["exempt"], 연말예상=_e["exempt"],
             처리="브라질국채 쿠폰 등 (과세 제외)"),
        dict(분류="🔵 분리과세", YTD실현=_y["separate"], 연말예상=_e["separate"],
             처리=f"{fin_full['threshold']/10_000:,.0f}만 이하분 (15.4% 원천징수로 종결)"),
        dict(분류="🟡 종합과세", YTD실현=_y["comprehensive"], 연말예상=_e["comprehensive"],
             처리="초과분 (누진세율 − 기납부14% 크레딧, 비교과세)"),
    ])
    st.dataframe(fin_df.style.format({"YTD실현": "₩{:,.0f}", "연말예상": "₩{:,.0f}"}),
                 width="stretch", hide_index=True)
    ec1, ec2, ec3 = st.columns(3)
    ec1.metric("예상 추가납부세액(종합과세분)", f"₩{fin_full['extra_tax']:,.0f}",
               fin_full["comp_method"], delta_color="off")
    ec2.metric(f"기타 종합소득({fin_full['year']})", f"₩{fin_full['other_income']:,.0f}",
               "설정 탭에서 연도별 입력", delta_color="off")
    ec3.metric("연말 임계 초과 전망", "⚠️ 초과" if fin_full["est_over"] else "이하",
               f"{fin_full['est_ratio']:.0%}", delta_color="off")
    st.caption("연말 예상 = YTD 실현 + 잔여 지급월×배당스케줄(현금흐름 탭과 동일 데이터). "
               "종합과세 세액은 비교과세(기납부 14% 크레딧 차감) 공식 적용 · 지방세 10% 포함. 실제 신고는 세무사 확인 필요.")

    st.markdown("##### 🔴 이월과세 (증여 후 1년 · 만료 전 매도 금지)")
    if taxsum["carryover"]:
        for w in taxsum["carryover"]:
            st.error(w["msg"])
    else:
        st.success("이월과세 기간 중 보유 종목의 매도 위험 없음.")

    st.markdown("##### 💰 증여세 (10년 합산 · 신고기한 = 증여월 말일+3개월)")
    st.caption("장남·차남은 미성년자로 확인되어 직계비속 공제 2,000만원을 적용합니다(성년 5,000만원 아님). "
               "부친·모친은 직계존속(성년) 공제 5,000만원. fx가 TODO인 증여 건은 근사환율(1,520.4원)로 추정 계산했습니다.")

    def _ddaytxt(days_left):
        return "완료" if days_left < 0 else f"D-{days_left}"

    if gt:
        gdf = pd.DataFrame(gt)
        gdf["신고기한"] = gdf.apply(lambda r: f"{r['filing_deadline']} ({_ddaytxt(r['days_left'])})", axis=1)
        gdf["근사치"] = gdf["has_estimate"].map(lambda x: "⚠️환율추정" if x else "")
        show = gdf[["recipient", "minor", "cumulative", "taxable", "tax_due_net", "신고기한", "근사치"]].rename(
            columns={"recipient": "수증자", "minor": "공제구분", "cumulative": "10년누적증여",
                     "taxable": "과세표준", "tax_due_net": "예상납부세액"})
        st.dataframe(show.style.format({"10년누적증여": "₩{:,.0f}", "과세표준": "₩{:,.0f}", "예상납부세액": "₩{:,.0f}"}),
                     width="stretch", hide_index=True)
        for r in gt_pending:
            if r["days_left"] <= 30:
                st.warning(f"⏰ {r['recipient']} 증여세 신고기한 {r['filing_deadline']} (D-{r['days_left']}) · 예상세액 ₩{r['tax_due_net']:,.0f}")
    else:
        st.caption("원장에 GIFT_IN 거래가 없습니다.")

    st.markdown("##### ⛔ RIA 인출금지 (매도 후 1년)")
    ria = taxsum["ria"]
    if ria["accounts"]:
        st.dataframe(pd.DataFrame(ria["accounts"]).rename(columns={
            "account": "계좌", "last_sell": "마지막매도", "unlock": "인출가능일", "days_to_unlock": "D-day"}),
            width="stretch", hide_index=True)
    for v in ria["violations"]:
        st.error(v["msg"])
    if not ria["violations"]:
        st.caption("RIA 인출금지 위반 없음.")

    st.markdown("##### 📈 금융소득종합과세 게이지 (YTD → 연말예상)")
    st.progress(min(1.0, fin_full["ratio"]),
                text=f"YTD ₩{fin_full['ytd']['taxable']:,.0f} / ₩{fin_full['threshold']:,.0f} ({fin_full['ratio']:.0%})")
    st.progress(min(1.0, fin_full["est_ratio"]),
                text=f"연말예상 ₩{fin_full['est']['taxable']:,.0f} / ₩{fin_full['threshold']:,.0f} ({fin_full['est_ratio']:.0%})"
                     + (" 🔴 초과 전망" if fin_full["est_over"] else ""))
    st.caption("커버드콜·맥쿼리·ELS 배당이 실제 지급(DIVIDEND 거래 입력)되면 누적됩니다. 브라질국채 쿠폰은 비과세로 제외.")
