# -*- coding: utf-8 -*-
"""
공용 엔진 모듈 — 김장섭 마삼룰 + 비교전략 9종
marsam_simulator.py 와 portfolio_dashboard.py 가 공유한다.
"""
import streamlit as st
import pandas as pd, numpy as np
import yfinance as yf
import requests
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# ──────────────────────────────── 엔진 (엑셀 v4 이식, 검증 완료) ────────────────────────────────
DEFAULTS=dict(cap=100_000, init_eq=1.0, fee=0.0004,
    m3_th=-0.03,                       # ① 나스닥 -3% 진입 임계 (수정가능)
    rb_step=0.025, rb_tick=0.10, rb_vup=0.05,   # ② 리밸 매도스텝/매도비율/반등올인(=2구간×스텝)
    mt_step=0.05, mt_tick=0.10,        # ③④ 말뚝 스텝/매수비율 (0.05=-50%표, 0.025=-25%표)
    zirp_auto=True,                    # 제로금리 기간에 진입한 말뚝박기는 자동으로 -25%표(2.5%)
    v_k=2, v_tick=1.0,                 # ⑤⑥ V자 반등 구간수 / 매수비율(1.0=올인)
    v_fail=1,                          # V올인 후 '최종 말뚝구간보다 몇 구간 더' 떨어지면 되파는지
    wait1=1, wait2=2, panic_n=4, up_n=8,        # 대기/공황/8일
    # ── 룰 ON/OFF (B0는 항상 ON 고정) ──
    on_A1=True, on_A2=True, on_B1=True, on_B3=True, on_B4=True, on_B5=True,
    on_D1=True, on_D2=True, on_E1=True,
    rebal_on=True,   # (하위호환: rebal_on=False면 A1/A2 동시 OFF)
    exec_next=False,     # True: 나스닥 -3%를 다음 거래일 종가에 체결(18장 표기). 기본은 당일(15장 1/5·4/26)
    mt_intraday=False,   # 말뚝 구간 판정: 종가(차트·체결가와 같은 기준, 15장 1차·18장 표). True=장중 저가(4장 본문·15장 2차)
    events_only=True,    # 룰이 뜬 날만 매매하고 그 사이엔 수량 유지(책). False=매일 목표비율 재조정
    rb_floor_allin=False,  # 19장 팁: 리밸로 0%가 되는 구간에서 전량매도 대신 올인, 그 가격을 새 기준가로
    peak0=None)          # 시뮬레이션 시작 전 전고점(옵션). None이면 시작일 가격부터 잰다

# 전략별 기본값 — 호출자가 명시하지 않은 항목만 덮는다(액션추천 등 기존 호출부 호환).
# 18장 테슬라·19장 비트코인: 변동성이 커서 리밸 5%마다 10%, 2구간(10%) 반등 시 올인. 금리표 자동전환 없음.
STRAT_DEFAULTS={
    "nonfirst":dict(rb_step=0.05, rb_vup=0.10, mt_step=0.05, zirp_auto=False),
    "rebal5":dict(rb_step=0.05, rb_vup=0.10),
}

# 미 연준 제로금리 기간(연방기금금리 0~0.25%). 책: "제로금리일 때 -25%표, 금리 인상 시기 -50%표".
ZERO_RATE_PERIODS=[("2008-12-16","2015-12-16"),("2020-03-15","2022-03-16")]

def _is_zirp(d):
    d=pd.Timestamp(d)
    return any(pd.Timestamp(a)<=d<pd.Timestamp(b) for a,b in ZERO_RATE_PERIODS)

RULE_TABLE=pd.DataFrame([
 ["A1","평시","기준가(전고점) 대비 −2.5%마다 (종가)","10% 매도 (래칫)"],
 ["A2","평시","바닥 구간에서 2구간 위 가격 회복, 또는 전고점 회복 (종가)","올인 → 그 구간가격=새 기준가"],
 ["A3","평시(옵션)","리밸로 주식 0%가 되는 구간 도달 (19장 팁)","전량매도 대신 올인 → 그 가격=새 기준가"],
 ["B0","위험 진입","나스닥 −3% (평시 중)","전고점 대비 말뚝 표 비율로 조정. 금리 따라 −25%/−50%표"],
 ["B1","말뚝박기","전고점 대비 한 구간 더 하락 (종가, 옵션: 장중 저가)","10% 매수 (래칫)"],
 ["B3","말뚝박기","바닥 구간에서 2구간 위 가격 회복 (종가)","V자 올인 (공황 해제 아님)"],
 ["B4","V올인 후","최종 말뚝구간보다 1구간 더 하락 (종가)","그 구간 비율로 되팔고 말뚝박기 재개"],
 ["B5","대기 중","나스닥 −3% 재발","대기기간 재시작. V올인 상태면 매도하지 않음"],
 ["D1","복귀","마지막 −3%일 +1달+1일 (공황 2달+1일)","전량 매수 → 평시"],
 ["D2","복귀","나스닥 8거래일 연속상승","전량 매수 → 평시 (공황도 해제)"],
 ["E1","공황","달력상 같은 달에 −3% 4회","대기 2달+1일. 해제(D1/D2) 전까지 유지"],
],columns=["번호","국면","트리거","액션"])

def _apply_targets(dates, px, tgt, cap=100_000, fee=0.0004):
    """일별 목표비율(tgt)을 순매매로 집행 — 모든 전략 공통 회계(공정비교)"""
    px=np.asarray(px,float); N=len(px); tgt=np.asarray(tgt,float)
    sh=cap/px[0]; cash=0.0; cost=cap; avg=px[0]
    O={k:np.zeros(N) for k in ["buy","sell","fee_","cash","sh","cost","avg","eq","tot","ratio","bh","peak_nv","m3","target"]}
    O["rule"]=[""]*N; peak=px[0]
    for i in range(N):
        p=px[i]; peak=max(peak,p); T=tgt[i]
        cv=sh*p; tot=cash+cv; tv=T*tot; delta=tv-cv
        b=max(0.0,min(delta,cash/(1+fee))); s=max(0.0,-delta); s=min(s,cv)
        cash=cash-b*(1+fee)+s*(1-fee)
        if b>0: cost+=b
        if s>0 and p>0: cost-=(s/p)*avg
        sh=sh+(b-s)/p; avg=cost/sh if sh>1e-9 else 0.0
        for k,val in [("buy",b),("sell",s),("fee_",(b+s)*fee),("cash",cash),("sh",sh),("cost",cost),
            ("avg",avg),("eq",sh*p),("tot",cash+sh*p),("ratio",(sh*p)/(cash+sh*p)),
            ("bh",cap*p/px[0]),("peak_nv",peak),("target",T)]: O[k][i]=val
    df=pd.DataFrame(O); df["date"]=pd.to_datetime(pd.Series(dates)).values; df["price"]=px
    df["dd"]=df["tot"]/df["tot"].cummax()-1; df["bh_dd"]=df["bh"]/df["bh"].cummax()-1
    return df

def _sma(a,n):
    a=np.asarray(a,float); out=np.full(len(a),np.nan)
    c=np.cumsum(np.insert(a,0,0))
    out[n-1:]=(c[n:]-c[:-n])/n
    return out
def _rsi(a,n):
    a=np.asarray(a,float); out=np.full(len(a),50.0)
    for i in range(n,len(a)):
        d=np.diff(a[i-n:i+1]); g=d[d>0].sum()/n; l=-d[d<0].sum()/n
        out[i]=100 if l==0 else 100-100/(1+g/l)
    return out

def strat_target(name, dates, px, ix, vix):
    """전략별 일별 목표 주식비율(0~1) 반환"""
    px=np.asarray(px,float); N=len(px)
    if name=="bh": return np.ones(N)
    if name=="ma200":
        m=_sma(px,200); return np.array([1.0 if (np.isnan(m[i]) or px[i]>m[i]) else 0.0 for i in range(N)])
    if name=="cross":
        m50=_sma(px,50); m200=_sma(px,200)
        return np.array([1.0 if (np.isnan(m200[i]) or m50[i]>m200[i]) else 0.0 for i in range(N)])
    if name=="turtle":   # 켄트너/채널: 20일 상단 돌파 매수, 10일 하단 이탈 청산
        t=np.zeros(N); pos=0
        for i in range(N):
            if i>=20:
                hi=px[i-20:i].max(); lo=px[i-10:i].min()
                if px[i]>hi: pos=1
                elif px[i]<lo: pos=0
            else: pos=1
            t[i]=pos
        return t
    if name=="dualmom":  # 절대모멘텀: 12개월(252일) 수익률>0 → 보유
        t=np.zeros(N)
        for i in range(N):
            if i>=252: t[i]=1.0 if px[i]/px[i-252]-1>0 else 0.0
            else: t[i]=1.0
        return t
    if name=="rsi2":     # 래리 코너스: 200MA 위 + RSI(2)<10 매수, >70 청산
        m=_sma(px,200); r=_rsi(px,2); t=np.zeros(N); pos=0
        for i in range(N):
            above = (not np.isnan(m[i])) and px[i]>m[i]
            if above and r[i]<10: pos=1
            if r[i]>70 or not above: pos=0
            t[i]=pos
        return t
    if name=="voltarget": # 변동성 타깃 20%: 목표비중=목표변동성/실현변동성(20일)
        ret=np.zeros(N); ret[1:]=px[1:]/px[:-1]-1; t=np.ones(N)
        for i in range(N):
            if i>=20:
                rv=np.std(ret[i-20:i])*np.sqrt(252)
                t[i]=min(1.0,0.20/rv) if rv>0 else 1.0
        return t
    if name=="vixavoid":  # VIX 리스크오프: VIX>25 현금, <20 풀투자, 사이 선형
        v=np.asarray(vix,float); t=np.ones(N)
        for i in range(N):
            vi=v[i]
            if np.isnan(vi): t[i]=1.0
            elif vi>=25: t[i]=0.0
            elif vi<=20: t[i]=1.0
            else: t[i]=(25-vi)/5
        return t
    return np.ones(N)

def run_engine(dates, px, ix, strategy="full", low=None, **kw):
    """low: 일별 장중 저가(선택). mt_intraday=True일 때만 말뚝 구간 판정에 쓴다(기본은 종가)."""
    P={**DEFAULTS,**STRAT_DEFAULTS.get(strategy,{}),**kw}
    if strategy=="marsam": P["rebal_on"]=False
    dates=pd.to_datetime(pd.Series(dates)).reset_index(drop=True)
    px=np.asarray(px,float); ix=np.asarray(ix,float); N=len(px)
    # 연계 안전장치: A1 OFF→A2 자동OFF, B3 OFF→B4 자동OFF, D1·D2 둘다OFF 방지
    if P.get("rebal_on",True)==False: P["on_A1"]=False
    if not P["on_A1"]: P["on_A2"]=False
    if not P["on_B3"]: P["on_B4"]=False
    if not P["on_D1"] and not P["on_D2"]: P["on_D1"]=True   # 영구대기 방지
    step=P["mt_step"]
    cap,fee=P["cap"],P["fee"]
    cols=["m3","up","cnt","panic","regime","mm","v","refp","rm","q","target",
          "buy","sell","fee_","cash","sh","cost","avg","eq","tot","ratio","bh","peak_nv"]
    out={k:np.zeros(N) for k in cols}; rules=[""]*N
    if strategy=="bh":
        sh0=cap/px[0]; pk=-1e9
        for i in range(N):
            pk=max(pk,px[i])
            out["sh"][i]=sh0; out["eq"][i]=out["tot"][i]=sh0*px[i]; out["ratio"][i]=1
            out["avg"][i]=px[0]; out["bh"][i]=cap*px[i]/px[0]; out["peak_nv"][i]=pk
            out["target"][i]=1; out["cash"][i]=0; out["q"][i]=px[i]; out["refp"][i]=pk
    else:
        # ── 김장섭 매뉴얼 1~5 + 10~14장 (공황·V자 반등·전고점/기준가) ──
        # 구간(row)은 항상 전고점(말뚝) 또는 기준가(리밸) 대비로 잰다. "2구간 상승"은 바닥에서
        # +10%가 아니라 '바닥 구간보다 두 칸 위 가격'이다(4·10·11장: 154.71→163.81, 136.51→154.71).
        lo_px=np.asarray(low,float) if (low is not None and P["mt_intraday"]) else px
        eps=1e-9
        rb_rows=max(1,int(round(P["rb_vup"]/P["rb_step"])))   # 리밸 V자 = 2구간(기본)
        mt_tick=P["mt_tick"]
        rebal_only=(strategy=="rebal5")
        lag=1 if P["exec_next"] else 0
        ixr=np.full(N,np.nan); ixr[1:]=ix[1:]/ix[:-1]-1      # 나스닥 일간 등락(신호일 기준)
        pk0=P["peak0"]
        peak=max(px[0],float(pk0)) if (pk0 is not None and np.isfinite(pk0)) else px[0]
        J=0;MM=0;V=0;LV=0;REF=peak;RM=0;Q=px[0];rel=pd.NaT;PAN=0;STEP=step;HIV=px[0]
        cash=cap*(1-P["init_eq"]); sh=cap*P["init_eq"]/px[0]; cost=cap*P["init_eq"]; avg=px[0] if sh>0 else 0
        mcnt={}
        for i in range(N):
            p=px[i]; peak=max(peak,p); m3=0; upn=0; cnt=0
            lp=min(p, lo_px[i]) if np.isfinite(lo_px[i]) else p
            if i>0 and not rebal_only:
                r=ixr[i-lag]; m3=1 if (np.isfinite(r) and r<=P["m3_th"]) else 0
                upn=(out["up"][i-1]+1) if (np.isfinite(r) and r>0) else 0
                ym=(dates[i-lag].year,dates[i-lag].month)  # 공황은 달력 월 기준(책 116쪽)
                if m3: mcnt[ym]=mcnt.get(ym,0)+1
                cnt=mcnt.get(ym,0)
            Jp,MMp,Vp,REFp,RMp,Qp,relp=J,MM,V,REF,RM,Q,rel
            hold_T=(sh*p)/(cash+sh*p) if (cash+sh*p)>0 else 0.0  # B1 OFF시 홀드용
            def lvl(price, st_): return int(max(0.0,1-price/peak)/st_+eps)
            def ratio(m): return min(1.0,m*mt_tick) if P["on_B1"] else hold_T
            rule=""
            if i>0:
                if m3:
                    newly_pan=(cnt>=P["panic_n"] and P["on_E1"] and not PAN)
                    if Jp==0:                               # B0: 평시 → 말뚝박기 진입
                        STEP=0.025 if (P["zirp_auto"] and _is_zirp(dates[i])) else step
                        PAN=1 if newly_pan else 0
                        V=0;MM=lvl(lp,STEP);T=ratio(MM);rule+="B0 "
                    else:                                   # B5: 대기 중 재발 → 기간만 재시작
                        if newly_pan: PAN=1
                        rule+=("B5 " if P["on_B5"] else "")
                        if Vp==1: T=P["v_tick"]             # 11·13장: V올인 상태면 -3%로는 팔지 않음
                        else:
                            MM=max(MMp,lvl(lp,STEP));T=ratio(MM)
                            if MM>MMp and P["on_B1"]: rule+="B1 "
                    if newly_pan: rule+="E1 "
                    J=1
                    rel=dates[i]+pd.DateOffset(months=(P["wait2"] if PAN else P["wait1"]))+pd.Timedelta(days=1)
                    RM=0;Q=min(Qp,p)
                elif Jp==1:
                    d2=P["on_D2"] and upn>=P["up_n"]
                    reentry=d2 or (P["on_D1"] and pd.notna(relp) and dates[i]>=relp)
                    if reentry:
                        rule+=("D2 " if d2 else "D1 ")
                        # V올인으로 이미 들고 있던 동안의 고점이 리밸 기준(15장 2022년 3/29 178.96)
                        REF=max(p,HIV) if Vp==1 else p
                        J=0;V=0;MM=0;RM=0;Q=p;T=1.0;rel=pd.NaT;PAN=0
                    else:
                        J=1;rel=relp;RM=0
                        if Vp==1:                           # 12·13장: 공황 끝까지 홀드, 단 1구간 더 빠지면 복귀
                            HIV=max(HIV,p)
                            fail=peak*(1-(LV+P["v_fail"])*STEP)
                            if P["on_B4"] and p<fail:
                                V=0;MM=max(LV+P["v_fail"],lvl(lp,STEP));T=ratio(MM);rule+="B4 "
                            else: V=1;T=P["v_tick"]
                            Q=min(Qp,p)
                        else:
                            MM=max(MMp,lvl(lp,STEP))
                            vthr=peak*(1-(MM-P["v_k"])*STEP)
                            if P["on_B3"] and MM>=P["v_k"] and p>=vthr:
                                V=1;LV=MM;HIV=p;rule+="B3 ";T=P["v_tick"];Q=p
                            else:
                                V=0;T=ratio(MM);Q=min(Qp,p)
                                if MM>MMp and P["on_B1"]: rule+="B1 "
                else:
                    J=0;MM=0;V=0;rel=relp
                    rst=P["rb_step"]
                    rrows=rb_rows
                    if P["on_A1"] or rebal_only:
                        athr=REFp*(1-(RMp-rrows)*rst)
                        if (P["on_A2"] or rebal_only) and RMp>rrows and p>=athr:
                            rule+="A2 ";REF=athr;RM=0;Q=p;T=1.0     # 10장: 2구간 상승 지점이 기준가
                        else:
                            REF=max(REFp,p)
                            RM=0 if p>=REF else max(RMp,int((1-p/REF)/rst+eps))
                            if RM>RMp: rule+="A1 "
                            elif RMp>0 and RM==0: rule+="A2 "      # 2구간 전에 전고점 회복 → 전량 복귀
                            Q=p if p>=REF else min(Qp,p)
                            T=max(0.0,1-RM*P["rb_tick"])
                            if P["rb_floor_allin"] and RM>RMp and T<=eps:
                                rule=rule.replace("A1 ","")+"A3 ";REF=p;RM=0;Q=p;T=1.0
                    else:
                        REF=max(REFp,p);RM=0;Q=p if p>=REF else min(Qp,p);T=1.0
            else: T=P["init_eq"]
            panic=PAN
            # 이벤트 사이엔 수량 유지. B5·E1·D1처럼 비율이 그대로인 신호는 기간만 바꾸므로 매매하지 않는다.
            trade=(not P["events_only"]) or i==0 or abs(T-out["target"][i-1])>eps or "B0" in rule
            delta=T*(cash+sh*p)-sh*p if trade else 0.0
            b=max(0.0,min(delta,cash/(1+fee))); s=max(0.0,-delta)
            if s>sh*p: s=sh*p
            cash=cash-b*(1+fee)+s*(1-fee)
            if b>0: cost+=b
            if s>0 and p>0: cost-=(s/p)*avg
            sh=sh+(b-s)/p; avg=cost/sh if sh>1e-9 else 0.0
            for k,v_ in [("m3",m3),("up",upn),("cnt",cnt),("panic",panic),("regime",J),("mm",MM),("v",V),
                ("refp",REF),("rm",RM),("q",Q),("target",T),("buy",b),("sell",s),("fee_",(b+s)*fee),
                ("cash",cash),("sh",sh),("cost",cost),("avg",avg),("eq",sh*p),("tot",cash+sh*p),
                ("ratio",(sh*p)/(cash+sh*p)),("bh",cap*p/px[0]),("peak_nv",peak)]: out[k][i]=v_
            rules[i]=rule.strip()
    df=pd.DataFrame(out); df["date"]=dates; df["price"]=px; df["ixic"]=ix; df["rule"]=rules
    df["dd"]=df["tot"]/df["tot"].cummax()-1; df["bh_dd"]=df["bh"]/df["bh"].cummax()-1
    return df

# ──────────────────────────────── 데이터 ────────────────────────────────
# ── 국내 주요종목 한글 사전 (한글 검색용) ──
KR_STOCKS={
 "삼성전자":"005930.KS","삼성전자우":"005935.KS","SK하이닉스":"000660.KS","하이닉스":"000660.KS",
 "LG에너지솔루션":"373220.KS","엘지에너지솔루션":"373220.KS","삼성바이오로직스":"207940.KS",
 "현대차":"005380.KS","현대자동차":"005380.KS","기아":"000270.KS","네이버":"035420.KS","NAVER":"035420.KS",
 "카카오":"035720.KS","셀트리온":"068270.KS","포스코홀딩스":"005490.KS","POSCO홀딩스":"005490.KS",
 "LG화학":"051910.KS","엘지화학":"051910.KS","삼성SDI":"006400.KS","현대모비스":"012330.KS",
 "KB금융":"105560.KS","신한지주":"055550.KS","하나금융지주":"086790.KS","삼성물산":"028260.KS",
 "삼성생명":"032830.KS","삼성화재":"000810.KS","한화에어로스페이스":"012450.KS","한화에어로":"012450.KS",
 "SK이노베이션":"096770.KS","LG전자":"066570.KS","엘지전자":"066570.KS","카카오뱅크":"323410.KS",
 "크래프톤":"259960.KS","삼성전기":"009150.KS","SK텔레콤":"017670.KS","KT":"030200.KS",
 "두산에너빌리티":"034020.KS","두산":"000150.KS","HD한국조선해양":"009540.KS","현대중공업":"329180.KS",
 "포스코퓨처엠":"003670.KS","LG":"003550.KS","SK":"034730.KS","현대글로비스":"086280.KS",
 "메리츠금융지주":"138040.KS","우리금융지주":"316140.KS","기업은행":"024110.KS","삼성증권":"016360.KS",
 "미래에셋증권":"006800.KS","한국전력":"015760.KS","한전":"015760.KS","KT&G":"033780.KS",
 "아모레퍼시픽":"090430.KS","LG생활건강":"051900.KS","엔씨소프트":"036570.KS","넷마블":"251270.KS",
 # 코스닥
 "에코프로비엠":"247540.KQ","에코프로":"086520.KQ","알테오젠":"196170.KQ","엔켐":"348370.KQ",
 "HLB":"028300.KQ","리노공업":"058470.KQ","펄어비스":"263750.KQ","셀트리온제약":"068760.KQ",
 "JYP":"035900.KQ","JYPEnt":"035900.KQ","위메이드":"112040.KQ","레인보우로보틱스":"277810.KQ",
 "클래시스":"214150.KQ","루닛":"328130.KQ","에스엠":"041510.KQ","SM":"041510.KQ","카카오게임즈":"293490.KQ",
 # 사용자 포트폴리오 종목 추가
 "하이비전시스템":"126700.KQ","하이비젼시스템":"126700.KQ",
 "KODEX Top5PlusTR":"315930.KS","맥쿼리인프라":"088980.KS",
 "KODEX 미국AI테크TOP10 타겟커버드콜":"483280.KS","KODEX 미국AI테크TOP10":"483280.KS",
 "KODEX 미국나스닥100 데일리커버드콜OTM":"494300.KS","KODEX 미국나스닥100데일리커버드콜OTM":"494300.KS",
}
@st.cache_data(ttl=3600, show_spinner=False)
def search_stocks(q):
    """종목명 검색: 한글사전 + Yahoo API. 반환 [(코드, 이름, 거래소)]"""
    q=q.strip()
    if not q: return []
    res=[]
    # 1) 한글/부분 사전 매칭
    for nm,code in KR_STOCKS.items():
        if q in nm or nm in q:
            res.append((code,nm,"KRX"))
    # 2) Yahoo 검색 (영어·티커)
    try:
        r=requests.get("https://query2.finance.yahoo.com/v1/finance/search",
            params={"q":q,"quotesCount":8,"newsCount":0},
            headers={"User-Agent":"Mozilla/5.0"},timeout=8)
        for it in r.json().get("quotes",[]):
            sym=it.get("symbol")
            if sym and not any(sym==c for c,_,_ in res):
                res.append((sym,it.get("shortname") or it.get("longname") or "",it.get("exchange","")))
    except Exception: pass
    # 중복제거·상위 8
    seen=set(); out=[]
    for c,n,e in res:
        if c not in seen: seen.add(c); out.append((c,n,e))
    return out[:8]

CRYPTO={"BTC","ETH","XRP","SOL","ADA","DOGE","BNB","DOT","AVAX","MATIC","LTC","LINK","TRX","SHIB","ATOM"}
def normalize_ticker(t):
    """코인 약칭 자동보정: btc → BTC-USD. 한글명이면 KR_STOCKS 사전에서 매핑."""
    t=t.strip()
    if t in KR_STOCKS: return KR_STOCKS[t]
    tu=t.upper()
    if tu in CRYPTO: return tu+"-USD"
    return tu

@st.cache_data(ttl=3600, show_spinner=False)
def get_name(ticker):
    """종목 정식명칭 조회 (없으면 티커 반환)"""
    try:
        info=yf.Ticker(ticker).info
        return info.get("longName") or info.get("shortName") or ticker
    except Exception:
        return ticker

def market_of(ticker):
    """티커로 시장 자동감지 → (신호지수, 지수명, 통화기호)"""
    t=ticker.upper().strip()
    if t.endswith("-USD"):
        return "^IXIC","나스닥","$"     # 코인 → 나스닥 신호(참고)
    if t.endswith(".KQ"):
        return "^KQ11","코스닥","₩"     # 코스닥 종목 → 코스닥 신호
    if t.endswith(".KS"):
        return "^KS11","코스피","₩"     # 코스피 종목 → 코스피 신호
    return "^IXIC","나스닥","$"          # 그 외 → 나스닥 신호

HIGH_YIELD_THRESHOLD = 0.08  # 최근 1년 분배금/현재가 비율이 이 이상이면 '고배당(월분배 등)'으로 판정

@st.cache_data(ttl=86400, show_spinner=False)
def _is_high_yield(ticker):
    """고배당·월분배 ETF(커버드콜 등) 판별. yfinance의 auto_adjust=True는 배당을 소급
    반영해서 과거 종가를 깎는데, 매달 1~2%씩 분배하는 상품은 이게 누적되면 과거 주가가
    실제 거래가보다 크게 낮게 왜곡된다(확인: 483280.KS·494300.KS, 2026-09-30).
    이런 종목은 원종가(auto_adjust=False)를 써야 실제 거래가·내 평단가와 비교가 맞는다.
    반대로 일반 종목은 액면분할 왜곡을 막기 위해 계속 auto_adjust=True를 쓴다."""
    try:
        tk = yf.Ticker(ticker)
        divs = tk.dividends
        if divs is None or divs.empty:
            return False
        cutoff = divs.index[-1] - pd.Timedelta(days=365)
        recent_total = float(divs[divs.index >= cutoff].sum())
        hist = tk.history(period="5d", auto_adjust=True)
        if hist.empty:
            return False
        price = float(hist["Close"].dropna().iloc[-1])
        return bool(price > 0 and recent_total / price > HIGH_YIELD_THRESHOLD)
    except Exception:
        return False


@st.cache_data(ttl=3600, show_spinner=False)
def load_data(ticker, start, end):
    """end는 그 날짜까지 포함한다(yfinance의 end는 미포함이라 하루 늘려 조회).
    코인은 주말에도 거래되므로 지수가 없는 날도 버리지 않고 직전 지수값을 이어 쓴다(등락 0 → 신호 없음)."""
    idx,idx_name,cur=market_of(ticker)
    end=(pd.Timestamp(end)+pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    crypto=ticker.upper().strip().endswith("-USD")
    t=yf.download(ticker,start=start,end=end,auto_adjust=not _is_high_yield(ticker),progress=False)
    x=yf.download(idx,start=start,end=end,auto_adjust=True,progress=False)
    v=yf.download("^VIX",start=start,end=end,auto_adjust=True,progress=False)
    vn=yf.download("^VXN",start=start,end=end,auto_adjust=True,progress=False)  # 나스닥100 변동성지수
    if t.empty or x.empty: return None
    def _col(d):
        if d is None or d.empty: return None
        c=d["Close"]; return c.iloc[:,0] if isinstance(c,pd.DataFrame) else c
    tc=_col(t); xc=_col(x); vc=_col(v); vnc=_col(vn)
    lc=t["Low"]; lc=lc.iloc[:,0] if isinstance(lc,pd.DataFrame) else lc   # 말뚝박기 장중 판정용
    df=pd.DataFrame({"price":tc,"ixic":xc.reindex(tc.index)})
    df["vix"]=vc.reindex(tc.index) if vc is not None else np.nan
    df["vxn"]=vnc.reindex(tc.index) if vnc is not None else np.nan
    df["low"]=lc.reindex(tc.index)
    if crypto:
        df[["ixic","vix","vxn"]]=df[["ixic","vix","vxn"]].ffill()
    df=df.dropna(subset=["price","ixic"]).reset_index()
    df.columns=["date","price","ixic","vix","vxn","low"]
    return df

@st.cache_data(ttl=86400, show_spinner=False)
def actual_price_factor(ticker, start, end, adjusted=True):
    """수정종가 → '그날 실제 거래가' 배율 시계열(날짜 인덱스). 액면분할(예: 테슬라 2022-08 3:1)과
    배당 조정을 되돌린다. 화면 표시 전용이며 전략 계산(비율·수익률)에는 쓰지 않는다."""
    try:
        end=(pd.Timestamp(end)+pd.Timedelta(days=1)).strftime("%Y-%m-%d")
        tk=yf.Ticker(ticker)
        h=tk.history(start=start,end=end,auto_adjust=False)
        if h.empty: return None
        idx=h.index.tz_localize(None).normalize()
        spl=tk.splits
        sf=pd.Series(1.0,index=idx)
        if spl is not None and len(spl):
            for d,r in spl.items():
                d=pd.Timestamp(d).tz_localize(None).normalize()
                if r and r>0: sf[idx<d]*=float(r)
        raw=pd.Series(h["Close"].to_numpy(),index=idx)*sf      # 분할 전 실제 종가
        base=h["Adj Close"] if (adjusted and "Adj Close" in h) else h["Close"]   # 엔진이 쓴 가격과 같은 기준
        adj=pd.Series(base.to_numpy(),index=idx)
        return (raw/adj).replace([np.inf,-np.inf],np.nan)
    except Exception:
        return None

# ──────────────────────────────── 차트 ────────────────────────────────
def chart_trend(df,ticker,idx_name="나스닥",cur="$",sim_start=None):
    """상단: 종가·전고점·전저점·평단가 + 나스닥-3% 수직선 (첨부 이미지 상단 재현).
    sim_start 이전 구간은 종가·지수만 있고, 평단가·전고점·전저점은 시작일부터 그린다."""
    fig=make_subplots(specs=[[{"secondary_y":True}]])
    if "q" in df.columns:
        fig.add_trace(go.Scatter(x=df["date"],y=df["q"],name="전저점",line=dict(width=0.8,color="#e8a5a5"),
            fill="tozeroy",fillcolor="rgba(240,200,200,0.25)"))
    fig.add_trace(go.Scatter(x=df["date"],y=df["peak_nv"],name=f"{ticker} 전고점",line=dict(dash="dot",color="#888",width=1.2)))
    fig.add_trace(go.Scatter(x=df["date"],y=df["price"],name=f"{ticker} 종가",line=dict(color=PRICE_COLOR,width=1.6)))
    av=df["avg"].replace(0,np.nan)
    fig.add_trace(go.Scatter(x=df["date"],y=av,name="평단가(전략)",line=dict(color="#2980b9",width=1.8,shape="hv")))
    # 보조축(y2)=VIX / VXN
    if "vix" in df.columns and df["vix"].notna().any():
        fig.add_trace(go.Scatter(x=df["date"],y=df["vix"],name="VIX (S&P500 공포)",
            line=dict(color="#8e44ad",width=1.2),opacity=0.85),secondary_y=True)
        fig.add_hline(y=20,line=dict(color="#8e44ad",width=0.6,dash="dot"),secondary_y=True)
        fig.add_hline(y=30,line=dict(color="#c0392b",width=0.6,dash="dot"),secondary_y=True)
    if "vxn" in df.columns and df["vxn"].notna().any():
        fig.add_trace(go.Scatter(x=df["date"],y=df["vxn"],name="VXN (나스닥100 공포)",
            line=dict(color="#e67e22",width=1.2),opacity=0.85),secondary_y=True)
    # 3번째 축(y3)=나스닥(신호지수) 복원
    if "ixic" in df.columns and df["ixic"].notna().any():
        fig.add_trace(go.Scatter(x=df["date"],y=df["ixic"],name=idx_name,yaxis="y3",
            line=dict(color="#bbb",width=1.1),opacity=0.65))
    for d in df.loc[df["m3"]==1,"date"]:
        fig.add_vline(x=d,line=dict(color="black",width=1.5))
    _sim_start_line(fig,df["date"].iloc[0],sim_start)
    fig.update_layout(height=370,margin=dict(l=60,r=70,t=30,b=10),
        legend=dict(orientation="h",y=-0.15),
        title=f"④ 가격 트렌드 · 전고점/전저점 · 평단가 · VIX/VXN · {idx_name} (수직선={idx_name} −3%)",
        yaxis3=dict(title=dict(text=idx_name,font=dict(color="#999")),overlaying="y",side="right",
            position=0.97,showgrid=False,tickfont=dict(color="#999")))
    fig.update_yaxes(title=f"주가({cur})",secondary_y=False)
    fig.update_yaxes(title="VIX / VXN",secondary_y=True,showgrid=False,range=[0,60])
    return fig

CHART_VIEWS=["가격","전고점 대비","누적수익률","상대강도"]
PRICE_COLOR="#8b1a1a"   # 종가 선: 시뮬레이션 전후 같은 색·같은 실선

# 국면 배경색: (라벨, 색). 공황이 가장 우선, 평시에 리밸로 일부 매도한 상태도 따로 칠한다.
REGIME_COLORS={"공황":"rgba(220,38,38,0.13)","V자 올인 보유":"rgba(34,197,94,0.13)",
               "말뚝박기":"rgba(249,115,22,0.13)","리밸 매도 중":"rgba(147,51,234,0.08)"}

# 책 사례의 1년 변동성: 애플 약 25%(리밸 2.5%), 테슬라 약 55%·비트코인 약 80%(5%). 그 사이를 기준으로 삼는다.
VOL_STEP_THRESHOLD=0.40

def vol_step_hint(dates,px,crypto=False):
    """최근 20거래일·최근 1년 연환산 변동성과 그에 맞는 권장 스텝. 데이터가 부족하면 None."""
    r=pd.Series(np.asarray(px,float)).pct_change().dropna()
    if len(r)<20: return None
    ann=np.sqrt(365 if crypto else 252)
    v20=float(r.tail(20).std()*ann); v1y=float(r.tail(365 if crypto else 252).std()*ann)
    return dict(vol20=v20,vol1y=v1y,step=0.05 if v1y>=VOL_STEP_THRESHOLD else 0.025)

def regime_spans(df):
    """시뮬레이션 구간을 국면별 연속 구간 [(라벨, 시작일, 끝일)]으로 나눈다. 평시(전량 보유)는 칠하지 않는다."""
    if "regime" not in df.columns:
        return []
    s=df[df["tot"].notna()] if "tot" in df.columns else df
    labs=[]
    for _,r in s.iterrows():
        if r.get("panic",0)==1: labs.append("공황")
        elif r.get("regime",0)==1: labs.append("V자 올인 보유" if r.get("v",0)==1 else "말뚝박기")
        elif r.get("rm",0)>0: labs.append("리밸 매도 중")
        else: labs.append(None)
    dates=list(pd.to_datetime(s["date"])); out=[]; i=0
    while i<len(labs):
        j=i
        while j+1<len(labs) and labs[j+1]==labs[i]: j+=1
        if labs[i]:
            out.append((labs[i],dates[i],dates[j+1] if j+1<len(dates) else dates[j]))
        i=j+1
    return out

def _add_regimes(fig,df):
    spans=regime_spans(df)
    for lab,x0,x1 in spans:
        fig.add_vrect(x0=x0,x1=x1,fillcolor=REGIME_COLORS[lab],line_width=0,layer="below",row="all",col=1)
    for lab in [l for l in REGIME_COLORS if l in {sp[0] for sp in spans}]:
        fig.add_trace(go.Scatter(x=[None],y=[None],mode="markers",name=lab,
            marker=dict(size=12,symbol="square",color=REGIME_COLORS[lab].replace("0.13","0.5").replace("0.08","0.4"))),
            row=1,col=1)

def _sim_start_line(fig,d0,sim_start):
    if sim_start is not None and pd.Timestamp(sim_start)>pd.Timestamp(d0):
        fig.add_vline(x=pd.Timestamp(sim_start),line=dict(color="#2563eb",width=1.5,dash="dash"))
        fig.add_annotation(x=pd.Timestamp(sim_start),y=1.02,yref="paper",text="시뮬레이션 시작",
            showarrow=False,font=dict(size=10,color="#2563eb"))

def chart_sim(df,ticker,idx_name="나스닥",cur="$",sim_start=None,view="가격",
              grid_step=0.05,bold_step=0.05,m3_th=-0.03,cap=100_000):
    """비교 시뮬레이터 메인 차트. 위: 보기(가격·전고점 대비·누적수익률·상대강도) + 국면 배경색,
    가운데: 주식비중, 아래: 신호지수 일간 등락 막대(−3% 기준선).
    df는 시작 전 구간(가격·지수만)을 포함할 수 있다. 종가 선은 전후 구간 모두 같은 실선이다."""
    fig=make_subplots(rows=3,cols=1,shared_xaxes=True,row_heights=[0.62,0.17,0.21],vertical_spacing=0.04,
                      specs=[[{"secondary_y":True}],[{}],[{}]])
    d=pd.to_datetime(df["date"]); px_=df["price"].astype(float)
    sim=df["tot"].notna() if "tot" in df.columns else pd.Series(True,index=df.index)
    i0=int(sim.idxmax()) if sim.any() else 0
    ix=df["ixic"].astype(float) if ("ixic" in df.columns and df["ixic"].notna().any()) else None
    ev=df[df["rule"].fillna("")!=""]
    def marks(y,secondary=False):
        fig.add_trace(go.Scatter(x=pd.to_datetime(ev["date"]),y=y,mode="markers+text",name="룰 이벤트",
            text=ev["rule"],textposition="top center",textfont=dict(size=9),
            marker=dict(size=7,color="black",symbol="diamond")),row=1,col=1,secondary_y=secondary)
    if view=="전고점 대비":
        pk=px_.cummax()
        if "peak_nv" in df.columns:
            pk=pk.where(~sim,df["peak_nv"].astype(float))
        dd=px_/pk-1
        lo=min(-0.12,float(dd.min())-0.03)
        k=1
        while k*grid_step<=-lo+1e-9:
            y=-k*grid_step; bold=abs(round(y/bold_step)-y/bold_step)<1e-6
            fig.add_hline(y=y,row=1,col=1,line=dict(color="#94a3b8" if bold else "#cbd5e1",
                          width=1 if bold else 0.6,dash="solid" if bold else "dot"))
            k+=1
        fig.add_trace(go.Scatter(x=d,y=dd,name=f"{ticker} 전고점 대비",line=dict(color=PRICE_COLOR,width=1.6)),
                      row=1,col=1)
        marks(dd[ev.index])
        fig.update_yaxes(title="낙폭",tickformat=".0%",dtick=bold_step,range=[lo,0.02],row=1,col=1,secondary_y=False)
    elif view=="누적수익률":
        stock=px_/float(px_.iloc[i0])-1
        fig.add_trace(go.Scatter(x=d,y=stock,name=f"{ticker} (=존버)",line=dict(color=PRICE_COLOR,width=1.6)),
                      row=1,col=1)
        if ix is not None:
            fig.add_trace(go.Scatter(x=d,y=ix/float(ix.iloc[i0])-1,name=idx_name,
                line=dict(color="#7f8c8d",width=1.2,dash="dash")),row=1,col=1)
        if "tot" in df.columns:
            fig.add_trace(go.Scatter(x=d[sim],y=df.loc[sim,"tot"]/cap-1,name="전략",line=dict(color="#2563eb",width=2)),
                          row=1,col=1)
        marks(stock[ev.index])
        fig.add_hline(y=0,row=1,col=1,line=dict(color="#94a3b8",width=1))
        fig.update_yaxes(title="시작일 대비",tickformat="+.0%",row=1,col=1,secondary_y=False)
    elif view=="상대강도" and ix is not None:
        rs=(px_/ix)/(float(px_.iloc[i0])/float(ix.iloc[i0]))*100
        fig.add_trace(go.Scatter(x=d,y=rs,name=f"{ticker} ÷ {idx_name}",line=dict(color=PRICE_COLOR,width=1.6)),
                      row=1,col=1)
        fig.add_trace(go.Scatter(x=d,y=rs.rolling(50,min_periods=10).mean(),name="50일 평균",
            line=dict(color="#f59e0b",width=1.4,dash="dash")),row=1,col=1)
        marks(rs[ev.index])
        fig.add_hline(y=100,row=1,col=1,line=dict(color="#94a3b8",width=1))
        fig.update_yaxes(title="상대강도(시작일=100)",row=1,col=1,secondary_y=False)
    else:
        s=df[sim]
        fig.add_trace(go.Scatter(x=pd.to_datetime(s["date"]),y=s["eq"],name="주식평가액",stackgroup="a",
            line=dict(width=0.5,color="#b7c9a3"),fillcolor="rgba(190,205,160,0.65)"),row=1,col=1,secondary_y=False)
        fig.add_trace(go.Scatter(x=pd.to_datetime(s["date"]),y=s["cash"],name="현금",stackgroup="a",
            line=dict(width=0.5,color="#e6d84a"),fillcolor="rgba(240,225,80,0.75)"),row=1,col=1,secondary_y=False)
        fig.add_trace(go.Scatter(x=d,y=px_,name=f"{ticker}종가",line=dict(color=PRICE_COLOR,width=1.6)),
                      row=1,col=1,secondary_y=True)
        if "avg" in df.columns:
            fig.add_trace(go.Scatter(x=d,y=df["avg"].replace(0,np.nan),name="평단가(전략)",
                line=dict(color="#2980b9",width=1.6,shape="hv")),row=1,col=1,secondary_y=True)
        marks(ev["price"],secondary=True)
        fig.update_yaxes(title=f"금액({cur})",row=1,col=1,secondary_y=False)
        fig.update_yaxes(title=f"주가({cur})",showgrid=False,row=1,col=1,secondary_y=True)
    # 가운데: 주식비중(0~100%) — 10%씩 사고판 흐름이 계단으로 보인다
    if "ratio" in df.columns:
        fig.add_trace(go.Scatter(x=d[sim],y=df.loc[sim,"ratio"],name="주식비중",fill="tozeroy",
            line=dict(color="#2563eb",width=1.4,shape="hv"),fillcolor="rgba(37,99,235,0.12)"),row=2,col=1)
        fig.update_yaxes(title="주식비중",tickformat=".0%",range=[0,1.05],dtick=0.5,row=2,col=1)
    # 아래: 신호지수 일간 등락. 상승=빨강, 하락=파랑, 진입임계 이하=검정
    if ix is not None:
        r=ix.pct_change()
        col=["#111827" if (v<=m3_th) else ("#dc2626" if v>0 else "#2563eb") for v in r.fillna(0)]
        fig.add_trace(go.Bar(x=d,y=r,name=f"{idx_name} 일간 등락",marker_color=col,showlegend=False,
            hovertemplate="%{x|%Y-%m-%d} %{y:+.2%}<extra></extra>"),row=3,col=1)
        fig.add_hline(y=m3_th,row=3,col=1,line=dict(color="#111827",width=1,dash="dash"),
            annotation_text=f"{m3_th:.0%}",annotation_position="bottom left",annotation_font_size=10)
        fig.update_yaxes(title=idx_name,tickformat=".0%",row=3,col=1)
    _add_regimes(fig,df)
    for x in pd.to_datetime(df.loc[df["m3"]==1,"date"]):
        fig.add_vline(x=x,line=dict(color="black",width=1.2))
    _sim_start_line(fig,d.iloc[0],sim_start)
    fig.update_layout(height=600,margin=dict(l=70,r=60,t=30,b=10),bargap=0,
        legend=dict(orientation="h",y=-0.08),
        title=f"① {view} · 룰 이벤트 · 국면 배경 · 가운데=주식비중 · 아래={idx_name} 일간 등락 (세로선={idx_name} {m3_th:.0%})")
    return fig

def chart_perf(df,cur="$"):
    """총자산 vs 존버 + 아래 언더워터(각자 고점 대비 낙폭). 하락 방어를 눈으로 비교한다."""
    df=df[df["tot"].notna()]
    d=pd.to_datetime(df["date"])
    fig=make_subplots(rows=2,cols=1,shared_xaxes=True,row_heights=[0.6,0.4],vertical_spacing=0.06)
    fig.add_trace(go.Scatter(x=d,y=df["tot"],name="전략 총자산",line=dict(color="#c0392b",width=1.8)),row=1,col=1)
    fig.add_trace(go.Scatter(x=d,y=df["bh"],name="존버 B&H",line=dict(color="#2c3e50",width=1.4,dash="dot")),row=1,col=1)
    fig.add_trace(go.Scatter(x=d,y=df["bh_dd"],name="존버 낙폭",fill="tozeroy",
        line=dict(color="#64748b",width=1),fillcolor="rgba(100,116,139,0.18)"),row=2,col=1)
    fig.add_trace(go.Scatter(x=d,y=df["dd"],name="전략 낙폭",fill="tozeroy",
        line=dict(color="#c0392b",width=1.4),fillcolor="rgba(192,57,43,0.18)"),row=2,col=1)
    fig.update_yaxes(title=f"총자산({cur})",row=1,col=1)
    fig.update_yaxes(title="고점 대비",tickformat=".0%",row=2,col=1)
    fig.update_layout(height=420,margin=dict(l=70,r=60,t=30,b=10),
        legend=dict(orientation="h",y=-0.12),
        title=f"③ 총자산 vs 존버 · 아래=언더워터(고점 대비 낙폭) — 전략 MDD {df['dd'].min():.1%} / 존버 {df['bh_dd'].min():.1%}")
    return fig

def run_strategy(skey, dates, price, ixic, vix, vxn=None, low=None, **params):
    """전략키 하나로 마삼룰 계열/비교전략 계열을 모두 처리하는 공용 진입점.
    반환 df는 어떤 전략이든 'target'(권고 주식비중 0~1) 컬럼을 공통으로 갖는다."""
    if skey in MARSAM_KEYS:
        df = run_engine(dates, price, ixic, skey, low=low, **params)
    else:
        tgt = strat_target(skey, dates, price, ixic, vix)
        df = _apply_targets(dates, price, tgt, cap=params.get("cap", 100_000), fee=params.get("fee", 0.0004))
        ixv = np.asarray(ixic, float)
        m3_th = params.get("m3_th", DEFAULTS["m3_th"])
        df["m3"] = [1 if (i > 0 and ixv[i] / ixv[i-1] - 1 <= m3_th) else 0 for i in range(len(df))]
    df["vix"] = np.asarray(vix, float)
    if vxn is not None:
        df["vxn"] = np.asarray(vxn, float)
    df["ixic"] = np.asarray(ixic, float)
    return df

def regime_label(row):
    """run_strategy 결과 한 행을 사람이 읽을 국면 라벨로 변환."""
    if "regime" not in row.index:
        t = row.get("target", 1.0)
        if t >= 0.99: return "🟢 투자유지"
        if t <= 0.01: return "⚪ 현금대기"
        return f"🟡 부분투자 ({t:.0%})"
    if row.get("regime", 0) == 1:
        if row.get("panic", 0) == 1:
            return "🚨 공황(대기)"
        return "🟠 위험대응중 (V자올인)" if row.get("v", 0) == 1 else "🟠 위험대응중"
    return "🟢 평시"

# ──────────────────────────────── 전략 목록 ────────────────────────────────
STRATS={
 "🔴 마삼룰 전체 (김장섭)":"full",
 "🔴 마삼룰만 (평시리밸 OFF)":"marsam",
 "🔵 1등 외 종목 (리밸 5%+말뚝 5%, 18장)":"nonfirst",
 "🟠 리밸런싱만 (5%마다 10%, 19장 비트코인)":"rebal5",
 "⚫ 존버 (Buy & Hold)":"bh",
 "📈 200일 이평 추세 (메브 파버)":"ma200",
 "📈 50/200 골든크로스":"cross",
 "🐢 켄트너 채널돌파 (터틀)":"turtle",
 "🚀 절대 모멘텀 (안토나치)":"dualmom",
 "🔄 RSI(2) 평균회귀 (코너스)":"rsi2",
 "📊 변동성 타깃팅 20%":"voltarget",
 "😱 VIX 리스크오프":"vixavoid",
}
# 예전 이름으로 저장된 종목별 전략(settings.json)을 새 이름으로 이어준다.
# '1등 외 종목'은 원래 1등이 아닌 종목용 전략이라, 규칙이 바뀐 새 1등 외 종목(18장)으로 잇는다.
STRAT_ALIASES={
 "🔵 1등 외 종목 (리밸런싱 5%만, 21장)":"🔵 1등 외 종목 (리밸 5%+말뚝 5%, 18장)",
}
def strat_label(name):
    return STRAT_ALIASES.get(name,name)
MARSAM_KEYS={"full","marsam","nonfirst","rebal5","bh"}
