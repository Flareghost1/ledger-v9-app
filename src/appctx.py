# -*- coding: utf-8 -*-
"""
appctx.py — v9 전역 컨텍스트 (사이드바 전역 필터 + 탭 공유 계산)

v9 §2·3: 비교기준(기간)·자산군·종목 필터를 사이드바로 승격 — 모든 탭이 ctx를 통해
같은 필터를 참조한다. 자산군/종목은 '전체 선택' 체크박스 + 개별 체크박스.
비교기준은 pills(버튼행)로 즉시 전환.

ctx 필드:
  L, fx, owners, active_owners, owner_set, owner_label, owner, is_all, snap_key
  basis, basis_label, basis_date            # 기간 필터 (모든 탭 공통)
  all_classes, sel_classes, class_filter_on # 자산군 필터 (set)
  sel_assets, asset_filter_on               # 종목 필터 (asset_id set)
  pos, cash_rows, total, total_eq, cash_krw # 소유자 필터 반영 (실시간 평가 완료)
  pos_f, cash_rows_f                        # + 자산군·종목 필터 반영
  by_class, by_item                         # 소유자 기준 자산군/항목 시가 (파이·스냅샷용)
  SETTINGS, FIN_THRESHOLD
  fin_full                                  # 소유자 필터 반영 금융소득 3분류 (§10)
  L_tax                                     # 소유자 필터 반영 Ledger (세금 계산용)
  n_new_items                               # 이번 로드에서 자동 생성된 액션아이템 수
"""
from collections import defaultdict
from datetime import date, timedelta
from types import SimpleNamespace

import streamlit as st

from ledger import Ledger
import prices
import settings as SET
import snapshots as SNAP
import tax_rules as tx
import action_items as AI
import ips as IPS


def _multi_filter(options, key_prefix, labels=None):
    """전체선택/전체해제 버튼 + 개별 체크박스. 반환: (선택 set, 필터 활성 여부).
    체크 상태는 세션에 남아 탭을 옮겨도 유지된다."""
    options = list(options)
    for o in options:
        st.session_state.setdefault(f"{key_prefix}_{o}", True)
    c1, c2 = st.columns(2)
    if c1.button("전체선택", key=f"{key_prefix}__all", width="stretch"):
        for o in options:
            st.session_state[f"{key_prefix}_{o}"] = True
        st.rerun()
    if c2.button("전체해제", key=f"{key_prefix}__none", width="stretch"):
        for o in options:
            st.session_state[f"{key_prefix}_{o}"] = False
        st.rerun()
    sel = set()
    for o in options:
        lab = (labels or {}).get(o, str(o))
        if st.checkbox(lab, key=f"{key_prefix}_{o}"):
            sel.add(o)
    return sel, (sel != set(options))


def build():
    """사이드바 렌더 + 전역 컨텍스트 계산. dashboard.py에서 1회 호출."""
    L = Ledger()
    fx = _fx()
    owners = L.owners()

    with st.sidebar:
        st.header("⚙️ 전역 설정")
        owner_sel = st.multiselect("소유자(owner)", ["전체"] + owners, default=["본인"],
                                   help="여러 명을 함께 보려면 복수 선택. '전체' 선택 시 모든 소유자 합산.")
        if not owner_sel or "전체" in owner_sel:
            active_owners = list(owners)
            is_all = True
        else:
            active_owners = [o for o in owners if o in owner_sel]
            is_all = set(active_owners) == set(owners)
        owner_label = "전체" if is_all else "+".join(active_owners)
        owner_set = set(active_owners)

        # §3 기간: 드롭다운 대신 버튼행(pills) — 클릭 즉시 전환
        st.markdown("**📅 기간** — 모든 탭 공통")
        basis = st.pills("기간", SNAP.BASES + ["직접입력"], default="전월",
                         selection_mode="single", key="g_basis", label_visibility="collapsed")
        if basis is None:
            basis = "전월"
        if basis == "직접입력":
            basis_date = st.date_input("기준 날짜", value=date.today() - timedelta(days=30),
                                       max_value=date.today(), key="g_basis_date")
            basis_label = basis_date.isoformat()
        else:
            basis_date = SNAP.target_date_of(basis, date.today())
            basis_label = basis

    # ── 소유자 필터 반영 포지션·현금 (실시간 평가) ──
    pos = []
    for o in active_owners:
        pos += L.positions_list(o)
    for p in pos:
        v, cp, ok = prices.value_position(p, fx)
        p["_v"] = v
        p["_cp"] = cp
        p["_live"] = ok
        p["_pnl"] = p["_v"] - p["cost_krw"]
    total_eq = sum(p["_v"] for p in pos)
    cash_rows = []
    for o in active_owners:
        cash_rows += L.cash_list(o)
    cash_krw = sum(c["amount"] * (fx if c["ccy"] == "USD" else 1) for c in cash_rows)
    total = total_eq + cash_krw

    # ── §2 자산군·종목 필터 (체크박스 + 전체선택/전체해제) ──
    # 종목 목록은 선택된 자산군에 속한 것만 보여준다(자산군↔종목 동기화).
    all_classes = sorted({(p["asset_class"] or "기타") for p in pos}) + ["CASH"]
    class_of = {}     # asset_id -> asset_class
    asset_name = {}   # asset_id -> 표시명
    for p in pos:
        class_of.setdefault(p["asset_id"], p["asset_class"] or "기타")
        asset_name.setdefault(p["asset_id"], p["name"])

    with st.sidebar:
        with st.expander("🗂 자산군 필터", expanded=False):
            sel_classes, class_filter_on = _multi_filter(all_classes, "g_cls")
        asset_opts = sorted([a for a in asset_name if class_of[a] in sel_classes],
                            key=lambda a: asset_name[a])
        with st.expander(f"📌 종목 필터 ({len(asset_opts)}종)", expanded=False):
            if asset_opts:
                st.caption("선택한 자산군에 속한 종목만 표시됩니다.")
                sel_assets, asset_filter_on = _multi_filter(asset_opts, "g_ast", labels=asset_name)
            else:
                st.caption("선택된 자산군에 해당하는 종목이 없습니다.")
                sel_assets, asset_filter_on = set(), True
        st.caption(f"거래 {len(L.txns)}건 · 자산 {len(L.assets)}종 · 계좌 {len(L.accounts)}개")
        st.caption(f"USD/KRW {fx:,.1f}")
        if st.button("🔄 새로고침(원장 재로드)"):
            st.cache_data.clear()
            st.rerun()

    pos_f = [p for p in pos
             if (p["asset_class"] or "기타") in sel_classes and p["asset_id"] in sel_assets]
    cash_rows_f = cash_rows if "CASH" in sel_classes else []
    filter_on = class_filter_on or asset_filter_on

    # 필터 반영 집계 (현황 탭의 파이·합계·테이블이 모두 이걸 쓴다)
    total_eq_f = sum(p["_v"] for p in pos_f)
    cash_krw_f = sum(c["amount"] * (fx if c["ccy"] == "USD" else 1) for c in cash_rows_f)
    total_f = total_eq_f + cash_krw_f
    by_class_f = defaultdict(float)
    by_item_f = defaultdict(float)
    for p in pos_f:
        by_class_f[p["asset_class"] or "기타"] += p["_v"]
        by_item_f[p["name"]] += p["_v"]
    if cash_krw_f:
        by_class_f["CASH"] += cash_krw_f
        for c in cash_rows_f:
            by_item_f[f"현금({c['ccy']})"] += c["amount"] * (fx if c["ccy"] == "USD" else 1)

    # ── 자산군·항목별 시가 집계 (파이·스냅샷 상세 공유 — 필터와 무관하게 전체 기록) ──
    by_class = defaultdict(float)
    by_item = defaultdict(float)
    for p in pos:
        by_class[p["asset_class"] or "기타"] += p["_v"]
        by_item[p["name"]] += p["_v"]
    by_class["CASH"] += cash_krw
    for c in cash_rows:
        by_item[f"현금({c['ccy']})"] += c["amount"] * (fx if c["ccy"] == "USD" else 1)

    SETTINGS = SET.load_settings()
    FIN_THRESHOLD = SETTINGS.get("fin_income_threshold", 20_000_000)

    # §10: 세금은 소유자 필터만 반영 — 필터된 원장으로 계산 (기간 필터 무시)
    if is_all:
        L_tax = L
    else:
        L_tax = Ledger(txns=[t for t in L.txns if t["owner"] in owner_set],
                       assets=L.assets, accounts=L.accounts)
    fin_full = tx.financial_income_full(L_tax, pos, fx, threshold=FIN_THRESHOLD)

    # 액션아이템 자동 트리거는 화면 필터와 무관하게 전체 원장 기준으로 실행(idempotent)
    if is_all:
        pos_all, total_all, fin_full_all = pos, total, fin_full
    else:
        pos_all = L.positions_list()
        for p in pos_all:
            v, cp, ok = prices.value_position(p, fx)
            p["_v"], p["_cp"], p["_live"] = v, cp, ok
        cash_all = sum(c["amount"] * (fx if c["ccy"] == "USD" else 1) for c in L.cash_list())
        total_all = sum(p["_v"] for p in pos_all) + cash_all
        fin_full_all = tx.financial_income_full(L, pos_all, fx, threshold=FIN_THRESHOLD)
    goals_all = IPS.compliance(L, pos_all, total_all, SETTINGS, fin_full_all)
    try:
        n_new_items = AI.run_all_triggers(L, fin_full_all, SETTINGS.get("ips_goals", []),
                                          goals_result=goals_all)
    except Exception as e:
        n_new_items = 0
        st.warning(f"액션아이템 자동생성 경고: {e}")

    # 일별 스냅샷 (선택 조합별 독립 기록 — 필터 이전의 전체 값 기록)
    # 클라우드 배포는 디스크가 재시작 시 초기화되므로, 오늘자로 새로 기록됐을 때만
    # (매일 1회) 바로 Drive에 올려서 "자산 트렌드"가 조용히 유실되지 않게 한다.
    snap_key = owner_label
    try:
        wrote1 = SNAP.record_snapshot(snap_key, total, total_eq, cash_krw)
        wrote2 = SNAP.record_detail(snap_key, dict(by_class), dict(by_item))
        if wrote1 or wrote2:
            import gdrive_sync as GDRIVE
            GDRIVE.autopush_toast("asset_snapshots.csv", "asset_snapshots_detail.csv")
    except Exception as e:
        st.warning(f"스냅샷 기록 경고: {e}")

    return SimpleNamespace(
        L=L, fx=fx, owners=owners, active_owners=active_owners, owner_set=owner_set,
        owner_label=owner_label, owner=owner_label, is_all=is_all, snap_key=snap_key,
        basis=basis, basis_label=basis_label, basis_date=basis_date,
        all_classes=all_classes, sel_classes=sel_classes, class_filter_on=class_filter_on,
        sel_assets=sel_assets, asset_filter_on=asset_filter_on, asset_names=asset_name,
        class_of=class_of, filter_on=filter_on,
        pos=pos, cash_rows=cash_rows, total=total, total_eq=total_eq, cash_krw=cash_krw,
        pos_f=pos_f, cash_rows_f=cash_rows_f,
        total_f=total_f, total_eq_f=total_eq_f, cash_krw_f=cash_krw_f,
        by_class=dict(by_class), by_item=dict(by_item),
        by_class_f=dict(by_class_f), by_item_f=dict(by_item_f),
        SETTINGS=SETTINGS, FIN_THRESHOLD=FIN_THRESHOLD,
        fin_full=fin_full, L_tax=L_tax, n_new_items=n_new_items,
    )


@st.cache_data(ttl=60, show_spinner=False)
def _fx():
    return prices.fx_usdkrw()
