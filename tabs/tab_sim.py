# -*- coding: utf-8 -*-
"""🧪 시뮬레이션 (v9 §16·17 + 후속 스프린트)
구성: ① 종목 트렌드(나의 평단가 오버레이) ② 마삼룰 비교 시뮬레이터(2패널, 나의 평단가 오버레이)
      ③ 환율 차트(국가 검색 + BRL/CNY 크로스 계산 수정)

후속 변경:
- '마삼룰 시뮬레이션 vs 실제 내 투자' 섹션 삭제(종목 트렌드의 종가+나의 평단가 차트와 의미 중복)
- '보유종목 전략 시뮬레이션' 섹션 삭제(비교 시뮬레이터 A/B와 기능 중복)
- 종목 트렌드·비교 시뮬레이터 모두에 '나의 평단가'(계좌 통합, 실제 원가) 오버레이 추가
- 환율차트: BRLKRW=X/CNYKRW=X가 장기간(start/end) 조회에서 빈 데이터를 반환하는 문제 확인 →
  USD 레그(KRW=X ÷ BRL=X 등) 경유로 계산해 항상 안정적으로 가져오도록 수정 + 국가/통화명 검색
"""
from datetime import date, timedelta

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import prices
import engine as v6
from enums import norm_type
from tabs import shared

SIM_START_MODES = ["실제 투자일", "시작일", "직접 지정"]

# §17 환율 국가선택: 라벨 → (직접 KRW 크로스 티커 또는 None, USD 레그 티커, 표시 배율, 통화코드)
# direct가 있으면 우선 시도하고, 실패(빈 데이터)하면 usd_leg로 KRW=X와 교차계산한다.
FX_PAIRS = {
    "USD/KRW (미국 달러)": (None, None, 1, "USD"),          # KRW=X 자체가 이미 USD/KRW
    "BRL/KRW (브라질 헤알)": (None, "BRL=X", 1, "BRL"),
    "JPY/KRW (일본 엔, 100엔당)": ("JPYKRW=X", "JPY=X", 100, "JPY"),
    "EUR/KRW (유로)": ("EURKRW=X", "EUR=X", 1, "EUR"),
    "CNY/KRW (중국 위안)": (None, "CNY=X", 1, "CNY"),
}
# 국가/통화명 검색어 → 라벨 (부분일치로도 찾도록 아래에서 substring 매칭도 함께 씀)
COUNTRY_ALIASES = {
    "미국": "USD/KRW (미국 달러)", "달러": "USD/KRW (미국 달러)", "usd": "USD/KRW (미국 달러)",
    "브라질": "BRL/KRW (브라질 헤알)", "헤알": "BRL/KRW (브라질 헤알)", "brl": "BRL/KRW (브라질 헤알)",
    "일본": "JPY/KRW (일본 엔, 100엔당)", "엔": "JPY/KRW (일본 엔, 100엔당)", "jpy": "JPY/KRW (일본 엔, 100엔당)",
    "유럽": "EUR/KRW (유로)", "유로": "EUR/KRW (유로)", "eur": "EUR/KRW (유로)",
    "중국": "CNY/KRW (중국 위안)", "위안": "CNY/KRW (중국 위안)", "런민비": "CNY/KRW (중국 위안)", "cny": "CNY/KRW (중국 위안)",
}


def _search_pair(q):
    """검색어 → 라벨. 별칭 정확일치 우선, 없으면 별칭·라벨 부분일치."""
    q = (q or "").strip().lower()
    if not q:
        return None
    if q in COUNTRY_ALIASES:
        return COUNTRY_ALIASES[q]
    for alias, label in COUNTRY_ALIASES.items():
        if q in alias.lower() or alias.lower() in q:
            return label
    for label in FX_PAIRS:
        if q in label.lower():
            return label
    return None


def _section_trend(ctx, tradable):
    st.markdown("#### 📈 종목 트렌드 — 나의 평단가 포함")
    opt = {f"{p['name']} ({prices.ticker_of(p['price_source'])})": prices.ticker_of(p["price_source"])
           for p in tradable}
    sel = st.selectbox("종목", list(opt.keys()), key="v9_trend")
    tk = opt[sel]
    yrs = st.slider("기간(년)", 1, 5, 2, key="v9_trend_yr")
    data = v6.load_data(tk, str(date.today() - timedelta(days=int(365.25 * yrs))), str(date.today()))
    if data is None:
        st.error("데이터 조회 실패")
        return
    # 전략 평단가(파란 선)는 내가 실제로 투자를 시작한 날부터 그린다. 그 전은 종가·지수만 같은 선으로 이어 보여준다.
    invest_day = _first_invest_date(ctx, tk)
    sim_start, note = _resolve_sim_start("실제 투자일", data["date"].iloc[0].date(), data["date"].iloc[-1].date(),
                                         None, invest_day)
    in_sim = data["date"] >= pd.Timestamp(sim_start)
    sd = data[in_sim].reset_index(drop=True)
    pre = data[~in_sim].reset_index(drop=True)
    df = v6.run_strategy("full", sd["date"], sd["price"], sd["ixic"], sd["vix"],
                         vxn=sd["vxn"] if "vxn" in sd else None,
                         low=sd["low"] if "low" in sd else None)
    if len(pre):
        pre_df = pre[[c for c in ("date", "price", "ixic", "vix", "vxn") if c in pre.columns]].copy()
        pre_df["m3"] = (pre_df["ixic"].pct_change() <= v6.DEFAULTS["m3_th"]).astype(int)
        df = pd.concat([pre_df, df], ignore_index=True)
    idx, idx_name, cur = v6.market_of(tk)
    fig = v6.chart_trend(df, tk, idx_name, cur, sim_start=sim_start)
    if note:
        st.caption(f"ℹ️ 전략 평단가(파란 선)·전고점·전저점: {note}")

    asset_ids_for_ticker = [p["asset_id"] for p in ctx.pos if prices.ticker_of(p.get("price_source")) == tk]
    aid = asset_ids_for_ticker[0] if asset_ids_for_ticker else None
    if aid:
        dates_str = [pd.Timestamp(d).strftime("%Y-%m-%d") for d in data["date"]]
        series = shared.real_avg_cost_series(ctx.L, ctx.owner_set, aid, dates_str)
        avg_real = [a for _, a in series]
        fig.add_trace(go.Scatter(x=data["date"], y=avg_real, name="나의 평단가(실제·계좌통합)",
                                 line=dict(color="#16a34a", width=3), connectgaps=True))
        fig.update_layout(title=fig.layout.title.text + " · 초록 실선=나의 실제 평단가")
    st.plotly_chart(fig, width="stretch", key="v9_tr")
    if not aid:
        st.caption("이 종목의 원장 asset_id를 찾지 못해 '나의 평단가' 오버레이는 생략했습니다.")


def _first_invest_date(ctx, ticker):
    """원장에서 사이드바 소유자가 이 티커를 처음 보유하기 시작한 날. 기록이 없으면 None."""
    L = getattr(ctx, "L", None)
    if L is None or not ticker:
        return None
    aids = {aid for aid, a in L.assets.items()
            if (prices.ticker_of(a.get("price_source")) or "").upper() == ticker.upper()}
    days = [str(t["date"])[:10] for t in L.txns
            if t["asset_id"] in aids and t["owner"] in ctx.owner_set
            and norm_type(t["type"]) in ("OPEN_POS", "BUY", "GIFT_IN", "TRANSFER_IN")
            and "HISTORY" not in (t.get("tag") or "")]
    return date.fromisoformat(min(days)) if days else None


def _resolve_sim_start(mode, start, end, manual, invest_day):
    """시뮬레이션 시작일과 화면 안내문. 범위를 벗어나면 시작일로 돌린다."""
    if mode == "실제 투자일":
        if invest_day is None:
            return start, "원장에 이 종목 보유 기록이 없어 시작일부터 계산합니다."
        if invest_day < start:
            return start, (f"실제 투자일 {invest_day}이 시작일보다 앞이라 시작일부터 계산합니다. "
                           "시작일을 앞당기면 투자일부터 볼 수 있습니다.")
        if invest_day > end:
            return start, f"실제 투자일 {invest_day}이 종료일보다 뒤라 시작일부터 계산합니다."
        return invest_day, f"실제 투자일 {invest_day}부터 계산합니다(원장의 첫 매수·보유 기록)."
    if mode == "직접 지정":
        if manual < start or manual > end:
            return start, "지정한 날짜가 기간 밖이라 시작일부터 계산합니다."
        return manual, None
    return start, None


def _compare_panel(ctx, key, default_ticker):
    """§17: v6 마삼룰 비교 시뮬레이터 패널(컴팩트 포팅) — 종목·기간·전략 개별 설정.
    시작일~종료일은 차트 기간, 시뮬레이션 시작일은 그 안에서 실제 투자일·시작일·직접 지정 중 고른다.
    시뮬레이션 시작 전 구간은 가격·지수만 보여준다.
    입력한 티커가 보유 종목과 일치하면 나의 평단가(실제)를 자산구성 차트에 겹쳐 보여준다."""
    st.subheader(f"패널 {key}")
    c1, c2 = st.columns(2)
    ticker_raw = c1.text_input("종목 티커 (한국주식 005930.KS · 코인 BTC-USD)", default_ticker, key=f"v9cmp_t{key}")
    ticker = v6.normalize_ticker(ticker_raw)
    strat = c2.selectbox("전략", list(v6.STRATS), key=f"v9cmp_s{key}")
    skey = v6.STRATS[strat]
    c3, c4, c5 = st.columns(3)
    start = c3.date_input("시작일", date.today() - timedelta(days=365), key=f"v9cmp_a{key}")
    end = c4.date_input("종료일", date.today(), key=f"v9cmp_b{key}")
    cap = c5.number_input("원금($)", 10_000, 10_000_000, 100_000, 10_000, key=f"v9cmp_c{key}")
    s1, s2 = st.columns([2, 1])
    mode = s1.radio("시뮬레이션 시작일", SIM_START_MODES, horizontal=True, key=f"v9cmp_sm{key}",
                    help="이 날 100% 보유로 시작합니다. 그 전 기간은 추세 확인용으로 가격·지수만 표시")
    manual = s2.date_input("직접 지정 날짜", start, key=f"v9cmp_ss{key}", disabled=(mode != "직접 지정"))
    sim_start, sim_note = _resolve_sim_start(mode, start, end, manual, _first_invest_date(ctx, ticker))
    if sim_note:
        st.caption(f"ℹ️ {sim_note}")
    o1, o2 = st.columns(2)
    peak_prior = o1.checkbox("시작일 이전 최고가를 전고점으로 사용", False, key=f"v9cmp_pp{key}",
                             help="끄면(기본) 시뮬레이션 시작일 가격부터 전고점을 잽니다")
    show_actual = o2.checkbox("당시 실제 주가로 표시 (액면분할·배당 조정 전)", False, key=f"v9cmp_ap{key}",
                              help="표시만 바뀌고 비율·수익률 계산은 같습니다. 예: 테슬라 2022년 1/3 399.93 → 1,199.78")

    # §12: 마삼룰 상세 설정 — 나스닥 진입임계의 −10% 하한 제한을 없앴다(−50%까지).
    # 리밸 스텝·반등·말뚝 스텝·제로금리는 전략마다 책의 기본값이 달라 전략별로 따로 기억한다.
    D = {**v6.DEFAULTS, **v6.STRAT_DEFAULTS.get(skey, {})}
    P = {}
    with st.expander("⚙️ 마삼룰 상세 설정 (마삼룰 계열 전략에만 적용)"):
        st.caption("값을 바꾸면 즉시 재계산됩니다. B0(−3% 진입)은 마삼룰 근간이라 항상 ON. "
                   "리밸·말뚝 스텝과 제로금리 표는 전략별 책 기본값으로 시작합니다(1등 외·리밸런싱만: 5%).")
        b1, b2, b3 = st.columns(3)
        P["fee"] = b1.number_input("수수료(%)", 0.0, 1.0, 0.04, 0.01, key=f"v9cmp_fee{key}") / 100
        P["m3_th"] = b2.number_input("① 지수 진입임계(%)", -50.0, -0.1, -3.0, 0.5,
                                     key=f"v9cmp_m3{key}",
                                     help="기본 −3%. 하한 제한 없이 −50%까지 지정 가능") / 100
        P["rb_step"] = b3.number_input("리밸 매도스텝(%)", 0.5, 20.0, D["rb_step"] * 100, 0.5,
                                       key=f"v9cmp_rs{key}_{skey}") / 100
        p1, p2, p3 = st.columns(3)
        P["rb_tick"] = p1.number_input("② 리밸 매도비율(%)", 5.0, 50.0, 10.0, 5.0, key=f"v9cmp_rt{key}") / 100
        P["rb_vup"] = p2.number_input("평시 반등올인(%)", 1.0, 20.0, D["rb_vup"] * 100, 0.5,
                                      key=f"v9cmp_vu{key}_{skey}",
                                      help="리밸 스텝의 2배(=2구간)가 책 기준. 스텝 5%면 10%") / 100
        P["mt_step"] = p3.number_input("③ 말뚝 스텝(%)", 1.0, 20.0, D["mt_step"] * 100, 0.5,
                                       key=f"v9cmp_ms{key}_{skey}",
                                       help="금리 인상기(-50%표) 기본 5. 아래 '제로금리 자동'이 켜져 있으면 "
                                            "제로금리 기간에 시작된 말뚝박기는 2.5(-25%표)로 자동 전환") / 100
        P["zirp_auto"] = st.checkbox("제로금리 기간 자동 -25%표 (2008.12~2015.12, 2020.03~2022.03)", D["zirp_auto"],
                                     key=f"v9cmp_zirp{key}_{skey}")
        p4, p5, p6 = st.columns(3)
        P["mt_tick"] = p4.number_input("④ 말뚝 매수비율(%)", 5.0, 50.0, 10.0, 5.0, key=f"v9cmp_mt{key}") / 100
        P["v_k"] = p5.number_input("⑤ V자 반등 스텝수", 1, 6, 2, 1, key=f"v9cmp_vk{key}")
        P["v_tick"] = p6.number_input("⑥ V자 매수비율(%)", 10, 100, 100, 10, key=f"v9cmp_vt{key}") / 100
        p7, p8 = st.columns(2)
        P["wait1"] = p7.number_input("대기-비공황(개월)", 1, 6, 1, 1, key=f"v9cmp_w1{key}")
        P["wait2"] = p8.number_input("대기-공황(개월)", 1, 12, 2, 1, key=f"v9cmp_w2{key}")
        st.markdown("**체결·판정 방식**")
        e1, e2, e3 = st.columns(3)
        P["exec_next"] = e1.checkbox("−3%를 다음 거래일에 체결", False, key=f"v9cmp_xn{key}",
                                     help="기본은 −3%가 뜬 날 종가에 체결(15장 1/5·4/26). "
                                          "18장 테슬라 표는 하루 뒤(1/6)로 적혀 있습니다")
        P["mt_intraday"] = e2.checkbox("말뚝 구간을 장중 저가로 판정", False, key=f"v9cmp_mi{key}",
                                       help="기본은 종가 판정(차트 선·체결가와 같은 기준, 15장 1차·18장 표). "
                                            "켜면 장중 저가로 판정(4장 본문·15장 2차 표). 체결은 어느 쪽이든 종가")
        P["events_only"] = e3.checkbox("룰이 뜬 날만 매매", True, key=f"v9cmp_eo{key}",
                                       help="책처럼 이벤트 사이에는 수량을 그대로 둡니다. "
                                            "끄면 매일 목표비율로 재조정합니다")
        P["rb_floor_allin"] = st.checkbox("리밸로 주식 0%가 되는 구간에서 전량매도 대신 올인, 그 가격부터 리밸 재시작 (19장 팁)",
                                          False, key=f"v9cmp_fa{key}")
        st.markdown("**룰 ON/OFF**")
        r1, r2, r3, r4, r5 = st.columns(5)
        P["on_A1"] = r1.checkbox("A1 평시매도", True, key=f"v9cmp_A1{key}")
        P["on_A2"] = r2.checkbox("A2 평시올인", True, key=f"v9cmp_A2{key}", disabled=not P["on_A1"])
        P["on_B1"] = r3.checkbox("B1/B2 말뚝매수", True, key=f"v9cmp_B1{key}")
        P["on_B3"] = r4.checkbox("B3 V자올인", True, key=f"v9cmp_B3{key}")
        P["on_B4"] = r5.checkbox("B4 V실패복귀", True, key=f"v9cmp_B4{key}", disabled=not P["on_B3"])
        r6, r7, r8, r9, _r10 = st.columns(5)
        P["on_B5"] = r6.checkbox("B5 −3%재발(기간 재시작)", True, key=f"v9cmp_B5{key}")
        P["on_D1"] = r7.checkbox("D1 기간재매수", True, key=f"v9cmp_D1{key}")
        P["on_D2"] = r8.checkbox("D2 8거래일재매수", True, key=f"v9cmp_D2{key}")
        P["on_E1"] = r9.checkbox("E1 공황(2달)", True, key=f"v9cmp_E1{key}")
        if not P["on_A1"]:
            P["on_A2"] = False
        if not P["on_B3"]:
            P["on_B4"] = False
        if not P["on_D1"] and not P["on_D2"]:
            st.warning("⚠️ D1·D2 둘 다 끄면 대기에서 못 빠져나옵니다 → D1 강제 ON")
            P["on_D1"] = True

    if not ticker:
        st.info("티커를 입력하세요")
        return
    if end <= start:
        st.error("종료일이 차트 시작일보다 뒤여야 합니다.")
        return
    idx, idx_name, cur = v6.market_of(ticker)
    data = v6.load_data(ticker, str(start), str(end))
    if data is None or len(data) < 20:
        st.error(f"'{ticker}' 데이터를 가져올 수 없습니다 (티커/기간 확인)")
        return
    in_sim = data["date"] >= pd.Timestamp(sim_start)
    sd = data[in_sim].reset_index(drop=True)
    pre = data[~in_sim].reset_index(drop=True)
    if len(sd) < 5:
        st.error("시뮬레이션 시작일 이후 데이터가 5거래일 미만입니다.")
        return
    P["peak0"] = float(pre["price"].max()) if (peak_prior and len(pre)) else None
    df = v6.run_strategy(skey, sd["date"], sd["price"], sd["ixic"], sd["vix"],
                         vxn=sd.get("vxn"), low=sd.get("low"), cap=cap, **P)
    ret = df["tot"].iloc[-1] / cap - 1
    bret = df["bh"].iloc[-1] / cap - 1
    mdd, bmdd = df["dd"].min(), df["bh_dd"].min()
    name = v6.get_name(ticker)
    high_yield = v6._is_high_yield(ticker)
    st.markdown(f"**📌 {name}** ({ticker}) · 신호지수 {idx_name}")
    if high_yield:
        st.caption("🟢 원종가(수정 안 함) 사용 — 최근 1년 분배금이 현재가의 "
                   f"{v6.HIGH_YIELD_THRESHOLD:.0%} 이상인 고배당·월분배 상품으로 판정돼, "
                   "배당 소급조정 없이 실제 거래가 그대로 차트·백테스트에 반영합니다.")
    elif show_actual:
        st.caption("🟣 가격은 당시 실제 거래가로 표시합니다. 계산은 수정종가(배당·액면분할 조정)로 하므로 비율·수익률은 같습니다.")
    else:
        st.caption("⚪ 수정종가(배당·액면분할 조정) 사용")
    m = st.columns(3)
    m[0].metric("전략 수익률", f"{ret:+.1%}", f"{ret-bret:+.1%}p vs 존버({bret:+.1%})")
    m[1].metric("전략 MDD", f"{mdd:.1%}", f"{mdd-bmdd:+.1%}p vs 존버({bmdd:.1%})", delta_color="off")
    m[2].metric("최종 총자산", f"{cur}{df['tot'].iloc[-1]:,.0f}",
                f"{cur}{df['tot'].iloc[-1]-df['bh'].iloc[-1]:+,.0f} vs 존버")
    vh = v6.vol_step_hint(data["date"], data["price"], crypto=ticker.upper().endswith("-USD"))
    if vh:
        now = P["rb_step"]
        tip = "리밸 스텝 설정과 같습니다" if abs(now - vh["step"]) < 1e-9 else f"지금 리밸 스텝은 {now:.1%}입니다"
        st.caption(f"📏 변동성: 최근 20일 {vh['vol20']:.0%} · 최근 1년 {vh['vol1y']:.0%} (연환산) → 권장 스텝 **{vh['step']:.1%}** "
                   f"({tip}). 책 사례 기준 1년 변동성 {v6.VOL_STEP_THRESHOLD:.0%} 이상이면 5%"
                   "(테슬라 약 55%·비트코인 약 80%), 미만이면 2.5%(애플 약 25%).")

    # 차트용: 시작일 이전 구간(가격·지수·−3% 표시만) + 시뮬레이션 구간
    pre_df = pd.DataFrame({"date": pre["date"], "price": pre["price"], "ixic": pre["ixic"]})
    if len(pre_df):
        pre_df["m3"] = (pre_df["ixic"].pct_change() <= P["m3_th"]).astype(int)
        pre_df["rule"] = ""
    full = pd.concat([pre_df, df], ignore_index=True) if len(pre_df) else df.copy()
    view = st.pills("차트 보기", v6.CHART_VIEWS, default="가격", selection_mode="single",
                    key=f"v9cmp_view{key}") or "가격"
    pct_view = full.copy()   # % 보기는 수정종가로 계산해야 분할 전후가 이어진다
    if show_actual and view == "가격":
        fac = v6.actual_price_factor(ticker, str(start), str(end), adjusted=not high_yield)
        if fac is not None and len(fac):
            f = fac.reindex(pd.to_datetime(full["date"]).dt.normalize(), method="ffill").fillna(1.0).to_numpy()
            for col in ("price", "avg", "peak_nv", "q"):
                if col in full.columns:
                    full[col] = full[col] * f
        else:
            st.caption("⚠️ 실제 거래가 조회에 실패해 수정종가로 표시합니다.")
    fig_alloc = v6.chart_sim(full if view == "가격" else pct_view, ticker, idx_name, cur, sim_start=sim_start,
                             view=view, grid_step=min(P["rb_step"], P["mt_step"]), bold_step=P["mt_step"],
                             m3_th=P["m3_th"], cap=cap)
    if view == "전고점 대비":
        st.caption("가로선은 말뚝 스텝(굵은 선)·리밸 스텝(점선) 구간입니다. 리밸런싱은 원래 '기준가' 대비로 재므로, "
                   "평시 올인(A2)으로 기준가가 바뀐 뒤에는 선과 조금 어긋날 수 있습니다.")
    elif view == "누적수익률":
        st.caption("시뮬레이션 시작일을 0%로 맞춰 종목(=존버)·지수·전략을 같은 축에 놓았습니다.")
    elif view == "상대강도":
        st.caption(f"종목 ÷ {idx_name}을 시작일=100으로 맞춘 선입니다. 오르면 지수보다 강하고, 50일 평균 아래로 꺾이면 "
                   "지수 대비 힘이 빠지는 중입니다 — 1등 종목 전략을 계속 쓸지 판단하는 참고선입니다.")
    asset_ids_for_ticker = [p["asset_id"] for p in ctx.pos if prices.ticker_of(p.get("price_source")) == ticker]
    aid = asset_ids_for_ticker[0] if asset_ids_for_ticker else None
    if aid and view == "가격":
        dates_str = [pd.Timestamp(d).strftime("%Y-%m-%d") for d in data["date"]]
        series = shared.real_avg_cost_series(ctx.L, ctx.owner_set, aid, dates_str)
        avg_real = [a for _, a in series]
        fig_alloc.add_trace(go.Scatter(x=data["date"], y=avg_real, name="나의 평단가(실제)",
                                       line=dict(color="#16a34a", width=3),
                                       connectgaps=True), row=1, col=1, secondary_y=True)
        st.caption(f"보유 중인 {name}과 일치 — 초록 실선이 나의 실제 평단가입니다.")
    st.plotly_chart(fig_alloc, width="stretch", key=f"v9cmp_ca{key}")
    st.plotly_chart(v6.chart_perf(full, cur), width="stretch", key=f"v9cmp_cp{key}")
    ev = full[full["rule"].fillna("") != ""][["date", "price", "rule", "target", "ratio", "buy", "sell", "avg"]].copy()
    ev[["target", "ratio"]] = ev[["target", "ratio"]] * 100
    ev.columns = ["날짜", "주가", "적용룰", "목표비율", "실제비율", "매수", "매도", "평단가"]
    with st.expander(f"📋 매매 이벤트 로그 ({len(ev)}건)"):
        st.dataframe(ev, width="stretch", height=260, hide_index=True, column_config={
            "날짜": st.column_config.DateColumn(format="YYYY-MM-DD"),
            "주가": st.column_config.NumberColumn(format="%.2f"),
            "목표비율": st.column_config.NumberColumn(format="%.0f%%"),
            "실제비율": st.column_config.NumberColumn(format="%.0f%%"),
            "매수": st.column_config.NumberColumn(format="%,.0f"),
            "매도": st.column_config.NumberColumn(format="%,.0f"),
            "평단가": st.column_config.NumberColumn(format="%.2f"),
        })


@st.cache_data(ttl=1800, show_spinner=False)
def _fx_cross_history(direct_tk, usd_leg_tk, years):
    """direct_tk를 먼저 시도(장기 조회에서 빈 데이터 반환 가능) → 실패 시 KRW=X ÷ usd_leg로 계산.
    (BRLKRW=X·CNYKRW=X가 yfinance의 start/end 장기 조회에서 빈 값을 반환하는 문제 확인됨 —
    period 단기 조회는 되지만 차트용 장기 히스토리는 안 됨. USD 레그 두 개는 항상 안정적으로 동작.)"""
    if direct_tk:
        h = prices.history(direct_tk, years=years)
        if h is not None and not h.empty:
            return h
    if usd_leg_tk is None:   # USD/KRW 자기 자신
        return prices.history("KRW=X", years=years)
    krw = prices.history("KRW=X", years=years)
    leg = prices.history(usd_leg_tk, years=years)
    if krw is None or krw.empty or leg is None or leg.empty:
        return None
    merged = pd.merge(krw, leg, on="date", suffixes=("_krw", "_leg"))
    merged["price"] = merged["price_krw"] / merged["price_leg"]
    return merged[["date", "price"]]


def _section_fx(ctx):
    st.markdown("#### 💱 환율 차트 (국가 선택)")
    st.caption("직접입력에 나라·통화 이름(예: 브라질, 헤알, 중국)을 입력하면 후보를 찾아드립니다.")
    search = st.text_input("🔍 나라/통화 이름으로 찾기 (비워두면 아래 목록에서 선택)", "", key="v9_fx_search")
    labels = list(FX_PAIRS.keys())
    default_idx = 0
    hit = _search_pair(search)
    if search.strip():
        if hit:
            default_idx = labels.index(hit)
            st.caption(f"✅ '{search}' → **{hit}** 선택됨")
        else:
            st.caption(f"'{search}'와 일치하는 통화가 없습니다 — 아래 목록에서 고르거나 "
                       "yfinance 티커를 알고 있으면 '직접 티커 입력'을 선택하세요.")

    fc1, fc2 = st.columns([2, 1])
    # 위젯 key에 검색어를 넣어, 검색이 바뀌면 새 위젯으로 취급되어 index가 실제로 적용되게 한다
    # (key가 고정이면 세션에 저장된 이전 선택이 index보다 우선해서 검색이 먹지 않는다).
    pair_label = fc1.selectbox("통화쌍", labels + ["직접 티커 입력(yfinance)"],
                               index=default_idx, key=f"v9_fx_pair_{hit or ''}")
    if pair_label == "직접 티커 입력(yfinance)":
        fx_tk = st.text_input("yfinance 환율 티커 (예: GBPKRW=X 또는 GBP=X)", "GBP=X", key="v9_fx_custom")
        direct_tk, usd_leg_tk, mult = (fx_tk if "KRW" in fx_tk else None,
                                       None if "KRW" in fx_tk else fx_tk, 1)
        pair_ccy = fx_tk.replace("KRW=X", "").replace("=X", "").upper() or None
    else:
        direct_tk, usd_leg_tk, mult, pair_ccy = FX_PAIRS[pair_label]
    fx_yrs = fc2.slider("조회기간(년)", 1, 10, 3, key="v9_fx_yr")

    fxh = _fx_cross_history(direct_tk, usd_leg_tk, fx_yrs)
    if fxh is None or fxh.empty:
        st.warning("환율 데이터를 가져오지 못했습니다(티커/네트워크 확인).")
        return
    disp = fxh["price"] * mult

    # §14: 통화 무관하게 '내 평균 취득환율'을 계산한다(USD 주식뿐 아니라 BRL 브라질채권 등도).
    #   평균취득환율 = Σ원화취득원가 ÷ Σ외화취득원가(수량×평단)
    avg_fx = None
    cur_rate = float(disp.iloc[-1])
    if pair_ccy:
        fx_pos = [p for p in ctx.pos if p["ccy"] == pair_ccy and p["qty"] > 1e-9 and p["avg_cost"]]
        cost_native = sum(p["avg_cost"] * p["qty"] for p in fx_pos)
        cost_krw_ccy = sum(p["cost_krw"] for p in fx_pos)
        avg_fx = (cost_krw_ccy / cost_native) if cost_native > 0 else None
        cur_native_val = sum(p["qty"] * (p["_cp"] if (p["_live"] and p["_cp"]) else p["avg_cost"])
                             for p in fx_pos)
    else:
        fx_pos, cur_native_val = [], 0.0

    if avg_fx:
        # 표시 배율(예: 100엔당)을 쓰는 통화는 지표도 같은 배율로 맞춘다
        avg_disp = avg_fx * mult
        fx_pnl = cur_native_val * (cur_rate / mult - avg_fx)
        k1, k2, k3, k4 = st.columns(4)
        k1.metric(f"현재 {pair_ccy}/KRW", f"{cur_rate:,.2f}")
        k2.metric("내 평균 취득환율", f"{avg_disp:,.2f}",
                  f"{cur_rate/avg_disp-1:+.1%}" if avg_disp else None, delta_color="off")
        k3.metric("환율 평가손익", f"₩{fx_pnl:,.0f}",
                  f"{pair_ccy} 자산 {cur_native_val:,.0f} 기준 · {len(fx_pos)}종목",
                  delta_color="normal" if fx_pnl >= 0 else "inverse")
        k4.metric(f"{fx_yrs}년 최저~최고", f"{disp.min():,.2f}~{disp.max():,.2f}")
    else:
        k1, k2 = st.columns(2)
        k1.metric("최근 환율", f"{cur_rate:,.2f}")
        k2.metric(f"{fx_yrs}년 최저~최고", f"{disp.min():,.2f}~{disp.max():,.2f}")
        if pair_ccy:
            st.caption(f"보유 중인 {pair_ccy} 표시 자산이 없어 평균 취득환율은 표시하지 않습니다.")

    fig_fx = go.Figure()
    fig_fx.add_trace(go.Scatter(x=fxh["date"], y=disp, name=pair_label,
                                line=dict(color="#2980b9", width=2)))
    if avg_fx:
        fig_fx.add_hline(y=avg_fx * mult, line=dict(color="#c0392b", width=2, dash="dot"),
                         annotation_text=f"내 평균 취득환율 {avg_fx*mult:,.2f}",
                         annotation_position="top left")
    fig_fx.update_layout(height=340, margin=dict(l=10, r=10, t=40, b=10),
                         title=f"{pair_label} 최근 {fx_yrs}년",
                         yaxis_title="원", legend=dict(orientation="h", y=-0.2))
    st.plotly_chart(fig_fx, width="stretch", key="v9_fx_chart")
    if avg_fx:
        st.caption(f"점선=원장 기준 내 평균 취득환율({pair_ccy}). 환율 평가손익은 {pair_ccy} 표시 "
                   "자산(주식·채권) 기준 — 외화 현금은 취득환율 이력이 없어 제외. "
                   "실시간 시세 없는 자산은 취득단가로 근사합니다.")


def render(ctx):
    tradable = [p for p in ctx.pos if p["_live"]]
    if tradable:
        _section_trend(ctx, tradable)
    else:
        st.info("상장 종목이 없어 종목 트렌드 대상이 없습니다.")

    st.divider()
    st.markdown("#### 🆚 마삼룰 비교 시뮬레이터 (최대 3개 나란히 전략 비교)")
    st.caption("기본은 1개이고, 아래에서 개수를 늘리면 2~3개를 나란히 놓고 비교합니다. 보유 중인 종목 티커를 입력하면 "
               "나의 실제 평단가가 자산구성 차트에 초록 실선으로 겹쳐 표시됩니다. "
               "각 패널의 '⚙️ 마삼룰 상세 설정'에서 룰 ON/OFF와 파라미터를 조정할 수 있습니다.")

    # §12: 종목코드 검색 — 한글·영어·티커로 찾아 아래 패널에 붙여넣는다.
    with st.expander("🔍 종목 코드 검색 (한글·영어·티커)"):
        q = st.text_input("종목명 입력 (예: 삼성전자 / apple / 비트코인은 BTC-USD)", key="v9_sim_search")
        if q:
            try:
                hits = v6.search_stocks(q)
            except Exception as e:
                hits = []
                st.warning(f"검색 실패: {e}")
            if hits:
                st.dataframe(pd.DataFrame(hits, columns=["코드(티커)", "종목명", "거래소"]),
                             width="stretch", hide_index=True, height=240)
                st.caption("💡 원하는 '코드(티커)'를 복사해 아래 패널의 티커칸에 붙여넣으세요 "
                           "(한국주식은 .KS/.KQ 포함).")
            else:
                st.info("검색 결과 없음. 영어명이나 정확한 티커로 다시 시도해보세요.")
    n = st.pills("시뮬레이션 개수", [1, 2, 3], default=1, selection_mode="single",
                 format_func=lambda k: f"{k}개", key="v9_sim_n") or 1
    cols = st.columns(n, gap="large") if n > 1 else [st.container()]
    for col, k in zip(cols, "ABC"):
        with col:
            _compare_panel(ctx, k, "NVDA")

    st.divider()
    _section_fx(ctx)
