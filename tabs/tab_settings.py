# -*- coding: utf-8 -*-
"""⚙️ 설정 (v8 동일 + v9: 종목별 전략 기본값 확인/초기화)"""
import pandas as pd
import streamlit as st

import settings as SET
import notion_sync as NS
import profile as PROFILE
import gdrive_sync as GDRIVE
import ips as IPS


def render(ctx):
    L, SETTINGS = ctx.L, ctx.SETTINGS
    st.markdown("#### ⚙️ 설정")
    st.caption(f"현재 프로필: **{PROFILE.get_profile()}**. 소유자·기간·자산군·종목 전역 필터는 왼쪽 사이드바에 있습니다.")

    # ── (a) 연도별 기타 종합소득 ──
    st.markdown("##### 💼 연도별 기타 종합소득 (근로·사업·연금 등)")
    st.caption("세금리포트의 종합과세(누진세 스택) 계산 베이스로 쓰입니다. 퇴사·이직·연금개시 등 "
               "어떤 소득 변화든 이 표 하나로 대응합니다. 미입력 연도는 0으로 처리(경고 표시).")
    oi_path = PROFILE.data_dir() / "other_income.csv"
    try:
        oi_df = pd.read_csv(oi_path, encoding="utf-8-sig", dtype={"year": "Int64"})
    except Exception:
        oi_df = pd.DataFrame(columns=["year", "category", "amount_krw", "note"])
    oi_edited = st.data_editor(
        oi_df, num_rows="dynamic", width="stretch", key="oi_editor",
        column_config={
            "year": st.column_config.NumberColumn("연도", min_value=2000, max_value=2100, step=1, format="%d"),
            "category": st.column_config.SelectboxColumn("구분", options=["근로", "사업", "연금", "기타"]),
            "amount_krw": st.column_config.NumberColumn("금액(원)", min_value=0, step=1_000_000, format="%d"),
            "note": st.column_config.TextColumn("메모"),
        })
    if st.button("💾 종합소득 저장", key="oi_save"):
        clean = oi_edited.dropna(subset=["year", "amount_krw"])
        clean.to_csv(oi_path, index=False, encoding="utf-8-sig")
        GDRIVE.autopush_toast("other_income.csv")
        st.success(f"저장 완료 ({len(clean)}행). 세금리포트에 즉시 반영됩니다.")
        st.rerun()

    st.divider()
    # ── (b) IPS 목표 관리 ──
    st.markdown("##### 🎯 IPS 목표 관리")
    st.caption("자신의 IPS(투자정책서)에 맞는 목표를 자유롭게 추가하세요. 현재값·진행률이 아래 표에 바로 나오고, "
               "목표 미달·임계 초과 시 🗒️액션아이템에 자동 등록됩니다(연 1회) — 별도 탭 없이 여기서 관리합니다.")
    goals = SETTINGS.get("ips_goals", [])
    if goals:
        def _target_txt(g):
            if g.get("target") is not None:
                return f"{g['target']:,.0f}"
            if g.get("target_by_year"):
                return "; ".join(f"{y}={v:,.0f}" for y, v in g["target_by_year"].items())
            return "미정"
        results = {r["id"]: r for r in IPS.compliance(L, ctx.pos, ctx.total, SETTINGS, ctx.fin_full)}

        def _cur_txt(g):
            r = results.get(g.get("id"))
            if not r:
                return "-"
            return f"{r['current']:,.1f}%" if r["unit"] == "%" else f"₩{r['current']:,.0f}"

        def _ratio_txt(g):
            r = results.get(g.get("id"))
            if not r or r["ratio"] is None:
                return "-"
            flag = "🔴" if (r["ratio"] > 1 and r["bad_over"]) else ("🟢" if r["ratio"] >= 1 else "")
            return f"{flag} {r['ratio']:.0%}"

        gdf = pd.DataFrame([dict(id=g.get("id"), 이름=g.get("label"),
                                 측정방식=SET.METRICS.get(g.get("metric"), (g.get("metric"),))[0],
                                 대상=g.get("match") or "(자동)", 현재값=_cur_txt(g),
                                 목표=_target_txt(g), 진행률=_ratio_txt(g))
                            for g in goals])
        st.dataframe(gdf, width="stretch", hide_index=True)
        del_id = st.selectbox("삭제할 목표", ["(선택)"] + [f"{g.get('id')}: {g.get('label')}" for g in goals], key="goal_del")
        if del_id != "(선택)" and st.button("🗑 목표 삭제"):
            gid = int(del_id.split(":")[0])
            SETTINGS["ips_goals"] = [g for g in goals if g.get("id") != gid]
            SET.save_settings(SETTINGS)
            GDRIVE.autopush_toast("settings.json")
            st.rerun()
    else:
        st.info("아직 목표가 없습니다. 아래에서 추가하세요. 예: 자산군 원금 합계(BOND_FX)=5억, "
                "계좌 연간 입금(ISA계좌)=연 4,000만, 종목 비중(AAPL), 금융소득 풀(자동).")

    with st.form("goal_add_form"):
        st.markdown("**새 목표 추가**")
        g1, g2 = st.columns(2)
        new_label = g1.text_input("이름 (예: 브라질국채 원금 5억)")
        metric_names = {v[0]: k for k, v in SET.METRICS.items()}
        new_metric_ko = g2.selectbox("측정방식", list(metric_names.keys()),
                                     help="자산군 합계 / 계좌 연간입금 / 종목 비중 / 금융소득 풀")
        new_metric = metric_names[new_metric_ko]
        g3, g4 = st.columns(2)
        class_opts = sorted({p["asset_class"] for p in L.positions_list() if p["asset_class"]})
        acct_opts_g = sorted({t["account"] for t in L.txns if t["account"]})
        asset_opts_g = sorted({p["asset_id"] for p in L.positions_list()})
        if new_metric == "asset_class_sum":
            new_match = g3.selectbox("대상 자산군", class_opts)
        elif new_metric == "account_deposit_annual":
            new_match = g3.selectbox("대상 계좌", acct_opts_g)
        elif new_metric == "position_weight_pct":
            new_match = g3.selectbox("대상 종목", asset_opts_g)
        else:
            new_match = ""
            g3.caption("금융소득 풀은 원장에서 자동 집계 — 대상 선택 불필요")
        new_target = g4.number_input("목표값 (원 또는 % · 0=목표 미정)", min_value=0.0, value=0.0, step=1.0, format="%.0f")
        new_year_target = st.text_input("연도별 목표 (계좌 연간입금 전용, 예: 2026=40000000; 2027=40000000)", "")
        if st.form_submit_button("➕ 목표 추가", type="primary") and new_label:
            tby = {}
            for part in new_year_target.split(";"):
                if "=" in part:
                    y, v = part.split("=", 1)
                    try:
                        tby[y.strip()] = float(v.strip().replace(",", ""))
                    except ValueError:
                        pass
            goal = dict(id=SET.next_goal_id(SETTINGS), label=new_label, metric=new_metric,
                        match=new_match, target=(new_target or None), target_by_year=(tby or None))
            SETTINGS.setdefault("ips_goals", []).append(goal)
            SET.save_settings(SETTINGS)
            GDRIVE.autopush_toast("settings.json")
            st.success(f"목표 추가: {new_label}")
            st.rerun()

    st.divider()
    # ── (c) 종목별 전략 기본값 (v9 §12 — 저장은 액션추천 탭에서) ──
    st.markdown("##### 🚦 종목별 전략 기본값")
    strat_map = SETTINGS.get("strategy_defaults", {})
    if strat_map:
        st.dataframe(pd.DataFrame([dict(종목=k, 전략=v) for k, v in strat_map.items()]),
                     width="stretch", hide_index=True)
        if st.button("🗑 전략 기본값 전체 초기화", key="strat_reset"):
            SETTINGS["strategy_defaults"] = {}
            SET.save_settings(SETTINGS)
            GDRIVE.autopush_toast("settings.json")
            st.rerun()
    else:
        st.caption("저장된 전략 기본값이 없습니다. 🚦 액션추천 탭에서 종목별 전략을 고르고 저장하세요.")

    st.divider()
    # ── (d) 임계값 ──
    st.markdown("##### 📏 임계값")
    new_thr = st.number_input("금융소득 종합과세 기준(원) — 세법 개정 시에만 변경",
                              value=int(ctx.FIN_THRESHOLD), step=1_000_000, format="%d", key="thr_input")
    if st.button("💾 임계값 저장", key="thr_save"):
        SETTINGS["fin_income_threshold"] = int(new_thr)
        SET.save_settings(SETTINGS)
        GDRIVE.autopush_toast("settings.json")
        st.success("저장 완료.")
        st.rerun()

    st.divider()
    # ── (e) Notion 연동 ──
    st.markdown("##### 🔗 Notion 연동 설정")
    st.caption("① notion.so/my-integrations 에서 통합(Integration) 생성 → 시크릿 토큰 복사. "
               "② Notion에 데이터베이스 생성 — 속성: 제목(제목), 카테고리(선택), 기한(날짜), 완료(체크박스). "
               "③ DB 우측상단 ⋯ → 연결 → 만든 통합 추가. ④ DB 링크의 32자리 ID를 아래에 입력.")
    cur_cfg = NS.load_config() or {}
    n1, n2 = st.columns(2)
    notion_token = n1.text_input("Notion 토큰 (secret_...)", value=cur_cfg.get("token", ""), type="password")
    notion_dbid = n2.text_input("데이터베이스 ID", value=cur_cfg.get("database_id", ""))
    nb1, nb2 = st.columns(2)
    if nb1.button("💾 Notion 설정 저장"):
        NS.save_config(notion_token.strip(), notion_dbid.strip())
        GDRIVE.autopush_toast("notion_config.json")
        st.success("저장 완료. 아래 연결 테스트로 확인하세요.")
    if nb2.button("🔌 연결 테스트"):
        ok, msg = NS.test_connection()
        (st.success if ok else st.error)(msg)

    st.divider()
    # ── (e-2) '본인' 프로필 비밀번호 ──
    st.markdown("##### 🔐 '본인' 프로필 비밀번호")
    st.caption("설정하면 프로필 선택 화면에서 '본인'을 고를 때마다 비밀번호를 묻습니다. "
               "비밀번호는 평문이 아니라 해시로 저장되고, 이 설정 파일은 저장소에 올라가지 않습니다. "
               "(배포 환경에서 OWNER_PASSWORD를 secret으로 넣었다면 그게 우선 적용됩니다.)")
    pw1, pw2 = st.columns(2)
    new_pw = pw1.text_input("새 비밀번호", type="password", key="owner_pw_new",
                            help="비우고 '해제'를 누르면 비밀번호 없이 쓸 수 있습니다.")
    new_pw2 = pw2.text_input("새 비밀번호 확인", type="password", key="owner_pw_new2")
    pb1, pb2 = st.columns(2)
    if pb1.button("💾 비밀번호 설정", key="owner_pw_save"):
        if not new_pw:
            st.error("비밀번호를 입력하세요.")
        elif new_pw != new_pw2:
            st.error("두 입력이 서로 다릅니다.")
        else:
            PROFILE.set_owner_password(new_pw)
            st.success("설정 완료 — 다음 프로필 선택부터 적용됩니다.")
    if pb2.button("🔓 비밀번호 해제", key="owner_pw_clear"):
        PROFILE.set_owner_password("")
        st.success("해제 완료.")
    st.caption("현재 상태: " + ("🔐 설정됨" if PROFILE.owner_password_required() else "🔓 없음"))

    st.divider()
    # ── (f) Google Drive 동기화 (v9 §12 — 클라우드 배포 시 데이터 영속성) ──
    st.markdown("##### ☁️ Google Drive 동기화")
    st.caption("Streamlit Cloud 등에 배포하면 로컬 디스크가 재배포 시 초기화되므로, "
               "Google Drive 폴더를 원본 삼아 시작할 때 자동으로 내려받고 여기서 수동으로 올립니다. "
               "인증정보는 코드에 넣지 않고 Streamlit **secrets**에만 둡니다(배포 안내서 참고). "
               "'샘플' 프로필은 동기화 대상이 아닙니다.")
    if not GDRIVE.is_configured():
        st.info("아직 미설정 상태입니다 — 로컬에서만 쓰신다면 그냥 두셔도 됩니다.")
    else:
        gc1, gc2, gc3 = st.columns(3)
        if gc1.button("🔌 연결 테스트", key="gdrive_test"):
            ok, msg = GDRIVE.test_connection()
            (st.success if ok else st.error)(msg)
        if gc2.button("⬇ Drive에서 내려받기", key="gdrive_pull",
                      help="Drive 폴더 내용으로 로컬 data/본인/ 을 덮어씁니다."):
            n, err = GDRIVE.pull_all()
            if err:
                st.error(err)
            else:
                st.success(f"{n}개 파일 내려받음.")
                st.cache_data.clear()
                st.rerun()
        if gc3.button("⬆ Drive로 올리기", key="gdrive_push",
                      help="로컬 data/본인/ 내용을 Drive 폴더에 올립니다(같은 이름은 덮어씀)."):
            n, err = GDRIVE.push_all()
            if err:
                st.error(err)
            else:
                st.success(f"{n}개 파일 업로드 완료.")
