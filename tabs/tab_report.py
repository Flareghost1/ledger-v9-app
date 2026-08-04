# -*- coding: utf-8 -*-
"""📋 1페이지 요약 리포트 (v8 동일)"""
from datetime import date

import streamlit as st

import report


def render(ctx):
    st.markdown("#### 📋 1페이지 요약 리포트 (상담창 붙여넣기용)")
    st.caption("이 md만 복사해서 상담창에 붙여넣으면 됩니다. 원시 데이터·코드는 넣지 않아 토큰을 아낍니다.")
    report_owner = ctx.active_owners[0] if len(ctx.active_owners) == 1 else None
    if report_owner is None and not ctx.is_all:
        st.caption(f"※ 복수 소유자({ctx.owner_label}) 선택 시 리포트는 '전체' 기준으로 생성됩니다.")
    md = report.build(ctx.L, report_owner, date.today())
    st.code(md, language="markdown")
    c = st.columns(2)
    c[0].download_button("⬇ 리포트 .md 다운로드", md.encode("utf-8-sig"),
                         f"report_{date.today().strftime('%Y%m%d')}.md")
    if c[1].button("💾 out/ 폴더에 저장"):
        p, _ = report.save(ctx.L, report_owner, date.today())
        st.success(f"저장: {p}")
