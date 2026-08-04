# -*- coding: utf-8 -*-
"""🗒️ 액션아이템 트래커 (v9 §11·15: IPS 미달 자동등록 통합, 배당 워딩 개선)"""
import pandas as pd
import streamlit as st

import action_items as AI
import notion_sync as NS
import gdrive_sync as GDRIVE


def render(ctx):
    st.markdown("#### 🗒️ 액션아이템 트래커")
    st.caption("배당 입금(실제 입고여부 확인+현금 용도 결정)·이월과세 D-30·금융소득 80%·증여세 D-14·"
               "연납입 미달·IPS 목표 미달 시 자동 생성됩니다. 체크하면 완료(DONE) 처리됩니다. "
               "거래원장과는 완전히 분리된 별도 파일(action_items.csv)입니다.")
    if ctx.n_new_items:
        st.info(f"🆕 이번 로드에서 액션아이템 {ctx.n_new_items}건이 자동 생성되었습니다.")

    items = AI.load_items()
    fc1, fc2, fc3 = st.columns(3)
    f_status = fc1.multiselect("상태", AI.STATUSES, default=["OPEN"], key="ai_f_status")
    f_cat = fc2.multiselect("카테고리", AI.CATEGORIES, default=[], key="ai_f_cat")
    f_sort = fc3.selectbox("정렬", ["기한임박순", "생성일순"], key="ai_f_sort")

    shown = [it for it in items
             if (not f_status or it["status"] in f_status)
             and (not f_cat or it["category"] in f_cat)]
    if f_sort == "기한임박순":
        shown.sort(key=lambda it: (it.get("due_date") or "9999-12-31", it.get("created_date", "")))
    else:
        shown.sort(key=lambda it: it.get("created_date", ""), reverse=True)

    if not shown:
        st.success("표시할 액션아이템이 없습니다. 🎉")
    else:
        st.caption("✏️ **메모** 칸은 직접 입력할 수 있습니다 — 진행상황·결정내용을 적어두세요. "
                   "수정 후 아래 '메모 저장'을 누르면 반영됩니다(완료 체크는 즉시 반영).")
        edit_df = pd.DataFrame([dict(완료=(it["status"] == "DONE"), id=it["id"], 카테고리=it["category"],
                                     제목=it["title"], 기한=it.get("due_date") or "",
                                     메모=it.get("memo") or "", 상세=it.get("detail") or "",
                                     상태=it["status"]) for it in shown])
        edited_items = st.data_editor(
            edit_df,
            column_config={
                "완료": st.column_config.CheckboxColumn(help="체크하면 DONE 처리 + 완료일 기록"),
                "id": st.column_config.TextColumn(disabled=True, width="small"),
                "카테고리": st.column_config.TextColumn(disabled=True, width="small"),
                "제목": st.column_config.TextColumn(disabled=True, width="large"),
                "기한": st.column_config.TextColumn(disabled=True, width="small"),
                "메모": st.column_config.TextColumn("메모 ✏️", width="large",
                                                    help="직접 입력하는 진행 메모"),
                "상세": st.column_config.TextColumn(disabled=True, width="large"),
                "상태": st.column_config.TextColumn(disabled=True, width="small"),
            },
            hide_index=True, width="stretch", key="ai_editor")

        by_id = {it["id"]: it for it in items}
        changed = False
        for _, row in edited_items.iterrows():
            it = by_id.get(row["id"])
            if not it:
                continue
            if bool(row["완료"]) != (it["status"] == "DONE"):
                AI.set_status(items, row["id"], "DONE" if row["완료"] else "OPEN")
                changed = True
        if changed:
            AI.save_items(items)
            GDRIVE.autopush_toast("action_items.csv")
            st.rerun()

        if st.button("💾 메모 저장", key="ai_memo_save"):
            n = 0
            for _, row in edited_items.iterrows():
                it = by_id.get(row["id"])
                if it is not None and (row["메모"] or "") != (it.get("memo") or ""):
                    it["memo"] = row["메모"] or ""
                    n += 1
            if n:
                AI.save_items(items)
                GDRIVE.autopush_toast("action_items.csv")
                st.success(f"메모 {n}건 저장 완료.")
                st.rerun()
            else:
                st.info("변경된 메모가 없습니다.")

    with st.expander("➕ 수동 액션아이템 추가"):
        with st.form("ai_manual_form"):
            m1, m2 = st.columns(2)
            ai_title = m1.text_input("제목")
            ai_cat = m2.selectbox("카테고리", AI.CATEGORIES)
            m3, m4 = st.columns(2)
            ai_due = m3.date_input("기한(선택)", value=None)
            ai_detail = m4.text_input("상세(선택)")
            if st.form_submit_button("추가", type="primary") and ai_title:
                AI.add_item(items, "수동", ai_cat, ai_title, detail=ai_detail,
                            due_date=ai_due.isoformat() if ai_due else "")
                AI.save_items(items)
                GDRIVE.autopush_toast("action_items.csv")
                st.rerun()

    with st.expander("🗑 항목 무시(DISMISS) 처리"):
        open_items = [it for it in items if it["status"] == "OPEN"]
        if open_items:
            dis_id = st.selectbox("무시할 항목", [f"{it['id']}: {it['title'][:60]}" for it in open_items], key="ai_dis")
            if st.button("무시 처리"):
                AI.set_status(items, dis_id.split(":", 1)[0], "DISMISSED")
                AI.save_items(items)
                GDRIVE.autopush_toast("action_items.csv")
                st.rerun()
        else:
            st.caption("OPEN 항목이 없습니다.")

    st.divider()
    st.markdown("##### 🔗 Notion 동기화")
    st.caption("휴대폰에서도 체크·수정하려면 설정 탭에서 Notion 토큰을 등록한 뒤 여기서 동기화하세요. "
               "동기화는 이 버튼을 눌렀을 때만 실행됩니다(네트워크 오류가 대시보드를 막지 않도록).")
    if st.button("🔄 Notion 동기화 (푸시 + 상태 가져오기)", key="ai_notion_sync"):
        items = AI.load_items()
        n_push, err1 = NS.push_open_items(items)
        n_pull, err2 = NS.pull_status(items)
        n_upd, err3 = NS.push_status_updates(items)
        AI.save_items(items)
        GDRIVE.autopush_toast("action_items.csv")
        for err in (err1, err2, err3):
            if err:
                st.error(err)
        if not any((err1, err2, err3)):
            st.success(f"동기화 완료 — Notion 생성 {n_push}건 · 완료 가져옴 {n_pull}건 · 완료 내보냄 {n_upd}건")
