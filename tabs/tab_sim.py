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
from tabs import shared

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
    df = v6.run_strategy("full", data["date"], data["price"], data["ixic"], data["vix"],
                         vxn=data["vxn"] if "vxn" in data else None)
    idx, idx_name, cur = v6.market_of(tk)
    fig = v6.chart_trend(df, tk, idx_name, cur)

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


def _compare_panel(ctx, key, default_ticker):
    """§17: v6 마삼룰 비교 시뮬레이터 패널(컴팩트 포팅) — 종목·기간·전략 개별 설정.
    입력한 티커가 보유 종목과 일치하면 나의 평단가(실제)를 자산구성 차트에 겹쳐 보여준다."""
    st.subheader(f"패널 {key}")
    c1, c2 = st.columns(2)
    ticker_raw = c1.text_input("종목 티커 (한국주식 005930.KS · 코인 BTC-USD)", default_ticker, key=f"v9cmp_t{key}")
    ticker = v6.normalize_ticker(ticker_raw)
    strat = c2.selectbox("전략", list(v6.STRATS), key=f"v9cmp_s{key}")
    c3, c4, c5 = st.columns(3)
    start = c3.date_input("시작일", date.today() - timedelta(days=365), key=f"v9cmp_a{key}")
    end = c4.date_input("종료일", date.today(), key=f"v9cmp_b{key}")
    cap = c5.number_input("원금($)", 10_000, 10_000_000, 100_000, 10_000, key=f"v9cmp_c{key}")

    # §12: 마삼룰 상세 설정 — 나스닥 진입임계의 −10% 하한 제한을 없앴다(−50%까지).
    P = {}
    with st.expander("⚙️ 마삼룰 상세 설정 (마삼룰 계열 전략에만 적용)"):
        st.caption("값을 바꾸면 즉시 재계산됩니다. B0(−3% 진입)은 마삼룰 근간이라 항상 ON.")
        b1, b2, b3 = st.columns(3)
        P["fee"] = b1.number_input("수수료(%)", 0.0, 1.0, 0.04, 0.01, key=f"v9cmp_fee{key}") / 100
        P["m3_th"] = b2.number_input("① 지수 진입임계(%)", -50.0, -0.1, -3.0, 0.5,
                                     key=f"v9cmp_m3{key}",
                                     help="기본 −3%. 하한 제한 없이 −50%까지 지정 가능") / 100
        P["rb_step"] = b3.number_input("리밸 매도스텝(%)", 0.5, 20.0, 2.5, 0.5, key=f"v9cmp_rs{key}") / 100
        p1, p2, p3 = st.columns(3)
        P["rb_tick"] = p1.number_input("② 리밸 매도비율(%)", 5.0, 50.0, 10.0, 5.0, key=f"v9cmp_rt{key}") / 100
        P["rb_vup"] = p2.number_input("평시 반등올인(%)", 1.0, 20.0, 5.0, 0.5, key=f"v9cmp_vu{key}") / 100
        P["mt_step"] = p3.number_input("③ 말뚝 스텝(%)", 1.0, 20.0, 5.0, 0.5, key=f"v9cmp_ms{key}",
                                       help="제로금리면 2.5, 비제로면 5") / 100
        p4, p5, p6 = st.columns(3)
        P["mt_tick"] = p4.number_input("④ 말뚝 매수비율(%)", 5.0, 50.0, 10.0, 5.0, key=f"v9cmp_mt{key}") / 100
        P["v_k"] = p5.number_input("⑤ V자 반등 스텝수", 1, 6, 2, 1, key=f"v9cmp_vk{key}")
        P["v_tick"] = p6.number_input("⑥ V자 매수비율(%)", 10, 100, 100, 10, key=f"v9cmp_vt{key}") / 100
        p7, p8 = st.columns(2)
        P["wait1"] = p7.number_input("대기-비공황(개월)", 1, 6, 1, 1, key=f"v9cmp_w1{key}")
        P["wait2"] = p8.number_input("대기-공황(개월)", 1, 12, 2, 1, key=f"v9cmp_w2{key}")
        st.markdown("**룰 ON/OFF**")
        r1, r2, r3, r4, r5 = st.columns(5)
        P["on_A1"] = r1.checkbox("A1 평시매도", True, key=f"v9cmp_A1{key}")
        P["on_A2"] = r2.checkbox("A2 평시올인", True, key=f"v9cmp_A2{key}", disabled=not P["on_A1"])
        P["on_B1"] = r3.checkbox("B1/B2 말뚝매수", True, key=f"v9cmp_B1{key}")
        P["on_B3"] = r4.checkbox("B3 V자올인", True, key=f"v9cmp_B3{key}")
        P["on_B4"] = r5.checkbox("B4 V실패복귀", True, key=f"v9cmp_B4{key}", disabled=not P["on_B3"])
        r6, r7, r8, r9, _r10 = st.columns(5)
        P["on_B5"] = r6.checkbox("B5 −3%재발복귀", True, key=f"v9cmp_B5{key}")
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
    idx, idx_name, cur = v6.market_of(ticker)
    data = v6.load_data(ticker, str(start), str(end))
    if data is None or len(data) < 20:
        st.error(f"'{ticker}' 데이터를 가져올 수 없습니다 (티커/기간 확인)")
        return
    df = v6.run_strategy(v6.STRATS[strat], data["date"], data["price"], data["ixic"], data["vix"],
                         vxn=data.get("vxn"), cap=cap, **P)
    ret = df["tot"].iloc[-1] / cap - 1
    bret = df["bh"].iloc[-1] / cap - 1
    mdd, bmdd = df["dd"].min(), df["bh_dd"].min()
    name = v6.get_name(ticker)
    st.markdown(f"**📌 {name}** ({ticker}) · 신호지수 {idx_name}")
    m = st.columns(3)
    m[0].metric("전략 수익률", f"{ret:+.1%}", f"{ret-bret:+.1%}p vs 존버({bret:+.1%})")
    m[1].metric("전략 MDD", f"{mdd:.1%}", f"{mdd-bmdd:+.1%}p vs 존버({bmdd:.1%})", delta_color="off")
    m[2].metric("최종 총자산", f"{cur}{df['tot'].iloc[-1]:,.0f}",
                f"{cur}{df['tot'].iloc[-1]-df['bh'].iloc[-1]:+,.0f} vs 존버")

    fig_alloc = v6.chart_alloc(df, ticker, idx_name, cur)
    asset_ids_for_ticker = [p["asset_id"] for p in ctx.pos if prices.ticker_of(p.get("price_source")) == ticker]
    aid = asset_ids_for_ticker[0] if asset_ids_for_ticker else None
    if aid:
        dates_str = [pd.Timestamp(d).strftime("%Y-%m-%d") for d in data["date"]]
        series = shared.real_avg_cost_series(ctx.L, ctx.owner_set, aid, dates_str)
        avg_real = [a for _, a in series]
        fig_alloc.add_trace(go.Scatter(x=data["date"], y=avg_real, name="나의 평단가(실제)",
                                       line=dict(color="#16a34a", width=3),
                                       connectgaps=True), secondary_y=True)
        st.caption(f"보유 중인 {name}과 일치 — 초록 실선이 나의 실제 평단가입니다.")
    st.plotly_chart(fig_alloc, width="stretch", key=f"v9cmp_ca{key}")
    st.plotly_chart(v6.chart_perf(df, cur), width="stretch", key=f"v9cmp_cp{key}")
    ev = df[df["rule"] != ""][["date", "price", "rule", "target", "ratio", "buy", "sell", "avg"]].copy()
    ev.columns = ["날짜", "주가", "적용룰", "목표비율", "실제비율", "매수", "매도", "평단가"]
    with st.expander(f"📋 매매 이벤트 로그 ({len(ev)}건)"):
        st.dataframe(ev, width="stretch", height=260, column_config={
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
    st.markdown("#### 🆚 마삼룰 비교 시뮬레이터 (종목 2개 나란히 전략 비교)")
    st.caption("임의 티커 2개를 나란히 놓고 전략을 비교합니다. 보유 중인 종목 티커를 입력하면 "
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
    left, right = st.columns(2, gap="large")
    with left:
        _compare_panel(ctx, "A", "NVDA")
    with right:
        _compare_panel(ctx, "B", "NVDA")

    st.divider()
    _section_fx(ctx)
