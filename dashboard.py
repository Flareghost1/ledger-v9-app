# -*- coding: utf-8 -*-
"""
═══════════════════════════════════════════════════════════════
 v9 통합 자산관리 대시보드 (거래원장 기반)
═══════════════════════════════════════════════════════════════
 설치:  pip install streamlit yfinance plotly pandas numpy openpyxl notion-client
 실행:  streamlit run dashboard.py

 · 입력은 거래원장(data/<프로필>/transactions.csv) 하나. 나머지는 전부 계산 결과.
 · v9: 프로필 선택(샘플/본인) · 탭별 모듈 분할(tabs/) · 전역 필터(기간·자산군·종목) 사이드바 승격 ·
       신한 [1721] 스타일 기간수익률 · 매매일지 이벤트 번호 마커 · 액션아이템 통합 ·
       종목별 전략 기본값 · 트렌드+시뮬 통합 · 현금흐름 예상vs실제 · 환율 국가선택
═══════════════════════════════════════════════════════════════
"""
import sys
from pathlib import Path

import streamlit as st

BASE = Path(__file__).resolve().parent
# v6 마삼룰 엔진(engine.py/analysis.py)은 src/ 안에 사본으로 들여왔다 —
# 옆 폴더(Simul v6)를 참조하면 클라우드 배포 시 그 폴더가 없어 앱이 죽는다.
# v6 엔진을 고치면 src/engine.py·src/analysis.py에도 반영해야 한다.
sys.path.insert(0, str(BASE / "src"))

import profile as PROFILE

st.set_page_config(page_title="v9 자산관리 (원장기반)", layout="wide")


def _profile_gate():
    """세션에 프로필이 없으면 선택 화면만 보여주고 멈춘다(다른 세션과 데이터 격리 보장)."""
    if PROFILE.get_profile():
        return
    st.title("🗂️ v9 통합 자산관리")
    st.caption("먼저 볼 데이터를 선택하세요. 브라우저 세션마다 독립적으로 기억됩니다.")
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("#### 🧪 샘플로 둘러보기")
        st.caption("가상의 인물 · 실제 금액이 아닌 예시 데이터입니다. 기능을 먼저 살펴볼 때 사용하세요.")
        if st.button("샘플 데이터로 시작", width="stretch"):
            PROFILE.set_profile("샘플")
            st.rerun()
    with c2:
        st.markdown("#### 🔐 본인 데이터")
        st.caption("실제 원장입니다.")
        if PROFILE.owner_password_required():
            pw = st.text_input("비밀번호", type="password", key="owner_pw")
            if st.button("본인 데이터로 시작", width="stretch"):
                if PROFILE.verify_owner_password(pw):
                    PROFILE.set_profile("본인")
                    st.rerun()
                else:
                    st.error("비밀번호가 올바르지 않습니다.")
        else:
            if st.button("본인 데이터로 시작", width="stretch"):
                PROFILE.set_profile("본인")
                st.rerun()
    st.stop()


_profile_gate()

import gdrive_sync as GDRIVE

# 세션당 1회만: 클라우드 배포(Streamlit Cloud 등) 환경에서 로컬 디스크가 비어있으면
# Google Drive에서 최신 데이터를 내려받는다. 미설정(로컬 개발 등)이면 조용히 skip.
if not st.session_state.get("_v9_gdrive_pulled") and GDRIVE.is_configured():
    n, err = GDRIVE.pull_all()
    st.session_state["_v9_gdrive_pulled"] = True
    if err:
        st.sidebar.warning(f"☁️ Drive 동기화 경고: {err}")
    elif n:
        st.cache_data.clear()

# 클라우드 배포 직후 Drive 미설정 상태에서 '본인'을 고르면 data/본인/transactions.csv 자체가
# 없어 아래 Ledger()가 죽는다 — 크래시 대신 설정 안내를 보여준다.
if PROFILE.get_profile() == "본인" and not (PROFILE.data_dir() / "transactions.csv").exists():
    st.error("🔐 '본인' 데이터가 아직 없습니다.")
    if GDRIVE.is_configured():
        st.caption("Google Drive 연결은 되어 있는데 폴더에 transactions.csv가 없습니다 — Drive 폴더 내용을 확인해주세요.")
    else:
        st.caption("로컬에서 쓰는 경우: data/본인/ 폴더에 원장 파일을 넣어주세요. "
                   "클라우드 배포인 경우: ⚙️설정 탭은 지금 열 수 없으니, "
                   "Streamlit Cloud의 Secrets에 [gdrive] 설정을 먼저 추가한 뒤 새로고침하세요.")
    if st.button("🧪 대신 샘플로 보기"):
        PROFILE.set_profile("샘플")
        st.rerun()
    st.stop()

import appctx
from tabs import (tab_status, tab_input, tab_upload, tab_journal, tab_tax,
                  tab_items, tab_action, tab_sim, tab_cash,
                  tab_report, tab_settings)

with st.sidebar:
    pc1, pc2 = st.columns([2, 1])
    pc1.caption(f"프로필: **{PROFILE.get_profile()}**")
    if pc2.button("전환", help="다른 프로필(샘플/본인)로 전환"):
        st.session_state.pop(PROFILE.SESSION_KEY, None)
        st.rerun()

st.title("🗂️ v9 통합 자산관리 — 거래원장 기반")
st.caption("입력은 거래원장 한 곳. 현황·손익·세금·현금흐름·액션아이템은 모두 원장에서 계산됩니다. "
           "기간·자산군·종목 필터는 왼쪽 사이드바에서 모든 탭에 공통 적용됩니다.")

ctx = appctx.build()

TABS = [
    ("📊 현황", tab_status),
    ("➕ 거래입력", tab_input),
    ("⬆️ 원장 업로드", tab_upload),
    ("📒 매매일지", tab_journal),
    ("🧾 세금리포트", tab_tax),
    ("🗒️ 액션아이템", tab_items),
    ("🚦 액션추천", tab_action),
    ("🧪 시뮬레이션", tab_sim),
    ("💵 현금흐름", tab_cash),
    ("📋 리포트", tab_report),
    ("⚙️ 설정", tab_settings),
]

for tab, (_, mod) in zip(st.tabs([label for label, _ in TABS]), TABS):
    with tab:
        mod.render(ctx)

st.divider()
st.caption("⚠️ 세율·세법은 코드에 박아넣은 가정값입니다(이월과세·RIA·양도세22%·종합소득 누진표·비교과세). 실제 신고는 세무 확인 필요. "
           "마삼룰은 세계 1등주 전제. 본 도구는 개인 참고용이며 투자·세무 판단과 책임은 본인에게 있습니다.")
