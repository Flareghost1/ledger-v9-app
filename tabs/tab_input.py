# -*- coding: utf-8 -*-
"""➕ 거래입력 — 거래원장 1줄 추가 (v8 동일)"""
from datetime import date

import streamlit as st

from ledger import append_transaction, next_txn_id
import gdrive_sync as GDRIVE


def render(ctx):
    L = ctx.L
    st.markdown("#### ➕ 거래 1줄 추가 (거래원장에 기록)")
    st.caption("이 프로그램의 유일한 손입력. 매수/매도 시 현금은 자동으로 차감·증가합니다. thesis(왜 샀는지)를 꼭 남기세요.")
    asset_opts = {f"{a['name_kr']} ({aid})": aid for aid, a in L.assets.items()}
    acct_opts = list(L.accounts.keys())
    with st.form("txn_form"):
        r1 = st.columns(4)
        f_date = r1[0].date_input("거래일", date.today())
        f_owner = r1[1].selectbox("owner", ctx.owners, index=ctx.owners.index(ctx.active_owners[0]))
        f_type = r1[2].selectbox("유형", ["BUY", "SELL", "DEPOSIT", "WITHDRAW", "DIVIDEND", "INTEREST",
                                          "FEE", "TAX", "GIFT_IN", "GIFT_OUT", "TRANSFER_IN", "TRANSFER_OUT",
                                          "REVALUE", "SPLIT"])
        f_acct = r1[3].selectbox("계좌", acct_opts + ["(직접입력)"])
        if f_acct == "(직접입력)":
            f_acct = st.text_input("계좌명 직접입력", "")
        r2 = st.columns(4)
        asset_choice = r2[0].selectbox("자산", ["(직접입력)"] + list(asset_opts.keys()))
        f_asset = st.text_input("자산 asset_id 직접입력 (티커/코드)", "") if asset_choice == "(직접입력)" else asset_opts[asset_choice]
        f_qty = r2[1].number_input("수량", value=0.0, step=1.0, format="%.4f")
        f_price = r2[2].number_input("단가", value=0.0, step=0.01, format="%.4f")
        f_ccy = r2[3].selectbox("통화", ["USD", "KRW", "BRL"])
        r3 = st.columns(4)
        f_fx = r3[0].number_input("환율(원/외화, KRW=1)", value=float(ctx.fx) if f_ccy == "USD" else 1.0, format="%.2f")
        f_fee = r3[1].number_input("수수료", value=0.0, format="%.2f")
        f_tax = r3[2].number_input("세금·원천징수", value=0.0, format="%.2f")
        f_cash = r3[3].text_input("현금계좌(cash_account, 공란=계좌동일)", "")
        f_tag = st.text_input("태그(MARSAM/RIA/ENERGY 등 · ; 로 복수)", "")
        f_note = st.text_area("thesis / note (왜 이 거래를 하는가)", "")
        submitted = st.form_submit_button("원장에 기록", type="primary")
    if submitted:
        if not f_asset or not f_acct:
            st.error("자산과 계좌는 필수입니다.")
        else:
            meta = L.assets.get(f_asset, {})
            row = dict(txn_id=next_txn_id(f_date.isoformat()), date=f_date.isoformat(), settle_date="",
                       owner=f_owner, account=f_acct, asset_id=f_asset,
                       asset_class=meta.get("asset_class", ""), type=f_type,
                       qty=f_qty or "", price=f_price or "", ccy=f_ccy, fx=f_fx,
                       amount=round((f_qty or 0) * (f_price or 0), 4) if f_qty and f_price else "",
                       fee=f_fee or "", tax=f_tax or "", cash_account=f_cash, link_id="",
                       tag=f_tag, note=f_note)
            append_transaction(row)
            GDRIVE.autopush_toast("transactions.csv")
            st.success(f"기록 완료: {row['txn_id']} {f_type} {f_asset} {f_qty}@{f_price}")
            st.cache_data.clear()
            st.rerun()
