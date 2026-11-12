# -*- coding: utf-8 -*-
"""⬆️ 원장 업로드 · 검증 · 교체 + 대사 (v8 동일)"""
import pandas as pd
import streamlit as st

import prices
import validate as V
import profile as PROFILE
import gdrive_sync as GDRIVE


def render(ctx):
    L = ctx.L
    st.markdown("#### ⬆️ 원장 업로드 · 검증 · 교체")
    st.caption(f"현재 프로필: **{PROFILE.get_profile()}**. "
               "① 현재 원장을 내려받아 → ② 엑셀/메모장에서 검증·수정 → ③ 다시 업로드하면 "
               "**엄격 검증** 후 통과 시에만 교체합니다. 교체 전 자동 백업됩니다.")

    cur_text = (PROFILE.data_dir() / "transactions.csv").read_text(encoding="utf-8-sig")
    c1, c2 = st.columns(2)
    c1.download_button("⬇ 현재 원장 다운로드 (transactions.csv)", cur_text.encode("utf-8-sig"),
                       "transactions.csv", mime="text/csv")
    c2.caption(f"현재 원장: {len(L.txns)}건")

    up = st.file_uploader("수정한 원장 CSV 업로드", type=["csv"], key="ledger_upload")
    if up is not None:
        raw = up.read()
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = raw.decode("cp949")
        rows = V.parse_csv_text(text)
        header = list(rows[0].keys()) if rows else []
        res = V.validate_rows(rows, header)
        st.markdown("##### 검증 결과")
        s = res["stats"]
        m = st.columns(4)
        m[0].metric("행수", s["rows"])
        m[1].metric("오류", len(res["errors"]), delta_color="inverse")
        m[2].metric("경고", len(res["warnings"]), delta_color="off")
        m[3].metric("TODO", s["todo"])
        st.caption(f"owners: {', '.join(s['owners'])} · types: {s['types']}")

        if res["errors"]:
            st.error(f"🔴 오류 {len(res['errors'])}건 — 수정 후 다시 업로드하세요. (교체 불가)")
            for e in res["errors"][:40]:
                st.write("✗", e)
        else:
            st.success("✅ 치명적 오류 없음 — 교체 가능합니다.")
        if res["warnings"]:
            with st.expander(f"⚠️ 경고 {len(res['warnings'])}건 (교체는 가능하나 확인 권장)"):
                for w in res["warnings"]:
                    st.write("•", w)

        with st.expander("업로드 원장 미리보기 (상위 20행)"):
            st.dataframe(pd.DataFrame(rows).head(20), width="stretch", hide_index=True)

        if not res["errors"]:
            st.warning("교체하면 현재 원장이 백업되고 이 파일로 대체됩니다. 자산 마스터도 자동 갱신됩니다.")
            if st.button("🔁 이 원장으로 교체", type="primary"):
                backup = V.backup_and_replace(text, PROFILE.data_dir())
                try:
                    import build_masters
                    build_masters.main(verify=False, data_dir=PROFILE.data_dir())
                except Exception as e:
                    st.info(f"마스터 자동갱신 경고: {e}")
                GDRIVE.autopush_toast("transactions.csv", "assets.csv", "accounts.csv")
                st.cache_data.clear()
                prices.live_price.cache_clear()
                prices.history.cache_clear()
                st.success(f"교체 완료 · 백업: {backup.name}")
                st.rerun()

    st.divider()
    st.markdown("##### 🧾 대사 (Reconciliation) — 증권사 앱 실제 잔고 대조")
    st.caption("실제 현금잔고를 입력하면 원장과의 차액을 보여줍니다. 불일치 시 원장이 틀린 것 → 거래 누락 확인.")
    rc = st.columns(4)
    rc_acct = rc[0].selectbox("계좌", sorted({c["account"] for c in L.cash_list()}), key="rec_acct")
    rc_ccy = rc[1].selectbox("통화", ["KRW", "USD"], key="rec_ccy")
    rc_actual = rc[2].number_input("실제 잔고", value=0.0, format="%.2f", key="rec_actual")
    if rc[3].button("대사 실행"):
        rc_owner = next((c["owner"] for c in L.cash_list() if c["account"] == rc_acct), ctx.active_owners[0])
        r = L.reconcile(rc_owner, rc_acct, rc_ccy, rc_actual)
        diff = r["diff"]
        st.metric(f"{rc_owner} · {rc_acct} {rc_ccy} 차액(실제−원장)", f"{diff:,.2f}",
                  "일치" if abs(diff) < 1 else "불일치 — 원장 확인 필요")
        st.caption(f"원장 {r['book']:,.2f} vs 실제 {r['actual']:,.2f}")
