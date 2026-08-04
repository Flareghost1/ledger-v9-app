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
    rb_step=0.025, rb_tick=0.10, rb_vup=0.05,   # ② 리밸 매도스텝/매도비율/반등올인
    mt_step=0.05, mt_tick=0.10,        # ③④ 말뚝 스텝(단일)/매수비율
    v_k=2, v_tick=1.0,                 # ⑤⑥ V자 반등 스텝수 / 매수비율(1.0=올인)
    wait1=1, wait2=2, panic_n=4, up_n=8,        # 대기/공황/8일
    # ── 룰 ON/OFF (B0는 항상 ON 고정) ──
    on_A1=True, on_A2=True, on_B1=True, on_B3=True, on_B4=True, on_B5=True,
    on_D1=True, on_D2=True, on_E1=True,
    rebal_on=True)   # (하위호환: rebal_on=False면 A1/A2 동시 OFF)

RULE_TABLE=pd.DataFrame([
 ["A1","상시","기준가 대비 −2.5%마다","10% 매도 (래칫)"],
 ["A2","상시","전저점 +5%(2구간) 반등","올인 → 올인가=새 기준가"],
 ["B0","위험 진입","나스닥 −3% 최초","낙폭의 말뚝 사다리 비율로 순조정"],
 ["B1","위험(비제로)","전고점 −5%마다","10% 매수 (래칫)"],
 ["B2","위험(제로금리)","전고점 −2.5%마다","10% 매수"],
 ["B3","위험","전저점 +2말뚝구간 반등","V자 올인"],
 ["B4","위험","V올인 후 전저점 이탈","사다리 복귀 (매도)"],
 ["B5","위험","대기 중 −3% 재발","사다리 복귀 + 대기 리셋"],
 ["D1","복귀","마지막 −3%일 +1달+1일 (공황 2달+1일)","전량 매수 → 평시"],
 ["D2","복귀","나스닥 8거래일 연속상승","조기 전량 매수"],
 ["E1","공황","1개월 내 −3% 4회","대기 2달+1일"],
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

def run_engine(dates, px, ix, strategy="full", **kw):
    P={**DEFAULTS,**kw}
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
        J=0;MM=0;V=0;REF=px[0];RM=0;Q=px[0];rel=pd.NaT
        cash=cap*(1-P["init_eq"]); sh=cap*P["init_eq"]/px[0]; cost=cap*P["init_eq"]; avg=px[0] if sh>0 else 0
        peak=px[0]
        for i in range(N):
            p=px[i]; peak=max(peak,p); m3=0; upn=0; cnt=0
            if i>0:
                r=ix[i]/ix[i-1]-1; m3=1 if r<=P["m3_th"] else 0
                upn=(out["up"][i-1]+1) if ix[i]>ix[i-1] else 0
                lo=dates[i]-pd.Timedelta(days=30)
                cnt=sum(1 for j in range(i) if out["m3"][j] and dates[j]>=lo)+m3
            panic=1 if cnt>=P["panic_n"] else 0
            Jp,MMp,Vp,REFp,RMp,Qp,relp=J,MM,V,REF,RM,Q,rel
            hold_T=(sh*p)/(cash+sh*p) if (cash+sh*p)>0 else 0.0  # B1 OFF시 홀드용
            rule=""
            if i>0:
                nd=p/peak-1
                if m3:
                    rule+=(("B5 " if P["on_B5"] else "") if Jp==1 else "B0 ")+("E1 " if (panic and P["on_E1"]) else "")
                    J=1;V=0;MM=max(MMp if Jp==1 else 0,int(max(0,-nd)/step))
                    rel=dates[i]+pd.DateOffset(months=(P["wait2"] if (panic and P["on_E1"]) else P["wait1"]))+pd.Timedelta(days=1)
                    REF=REFp;RM=0;Q=min(Qp,p);T=(min(1.0,MM*P["mt_tick"]) if P["on_B1"] else hold_T)
                elif Jp==1:
                    reentry=(P["on_D2"] and upn>=P["up_n"]) or (P["on_D1"] and pd.notna(relp) and dates[i]>=relp)
                    if reentry:
                        rule+=("D2 " if (P["on_D2"] and upn>=P["up_n"]) else "D1 ")
                        J=0;V=0;MM=0;REF=p;RM=0;Q=p;T=1.0;rel=pd.NaT
                    else:
                        J=1;MM=max(MMp,int(max(0,-nd)/step));rel=relp;RM=0
                        if Vp==1:
                            if p<Qp: V=0;rule+=("B4 " if P["on_B4"] else "");T=(min(1.0,MM*P["mt_tick"]) if P["on_B1"] else hold_T);Q=min(Qp,p);REF=REFp
                            else: V=1;T=1.0;Q=min(Qp,p);REF=REFp
                        else:
                            if P["on_B3"] and Qp>0 and p/Qp-1>=P["v_k"]*step:
                                V=1;rule+="B3 ";T=P["v_tick"];REF=p;Q=p
                            else:
                                V=0;T=(min(1.0,MM*P["mt_tick"]) if P["on_B1"] else hold_T);Q=min(Qp,p);REF=REFp
                                if MM>MMp and P["on_B1"]: rule+="B1 "
                else:
                    J=0;MM=0;V=0;rel=relp
                    if P["on_A1"]:
                        if P["on_A2"] and RMp>0 and Qp>0 and p/Qp-1>=P["rb_vup"]:
                            rule+="A2 ";REF=p;RM=0;Q=p;T=1.0
                        else:
                            REF=max(REFp,p)
                            RM=0 if p>=REF else max(RMp,int((1-p/REF)/P["rb_step"]))
                            if RM>RMp: rule+="A1 "
                            Q=p if p>=REF else min(Qp,p)
                            T=max(0.0,1-RM*P["rb_tick"])
                    else:
                        REF=max(REFp,p);RM=0;Q=p if p>=REF else min(Qp,p);T=1.0
            else: T=P["init_eq"]
            delta=T*(cash+sh*p)-sh*p
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

@st.cache_data(ttl=3600, show_spinner=False)
def load_data(ticker, start, end):
    idx,idx_name,cur=market_of(ticker)
    t=yf.download(ticker,start=start,end=end,auto_adjust=True,progress=False)
    x=yf.download(idx,start=start,end=end,auto_adjust=True,progress=False)
    v=yf.download("^VIX",start=start,end=end,auto_adjust=True,progress=False)
    vn=yf.download("^VXN",start=start,end=end,auto_adjust=True,progress=False)  # 나스닥100 변동성지수
    if t.empty or x.empty: return None
    def _col(d):
        if d is None or d.empty: return None
        c=d["Close"]; return c.iloc[:,0] if isinstance(c,pd.DataFrame) else c
    tc=_col(t); xc=_col(x); vc=_col(v); vnc=_col(vn)
    df=pd.DataFrame({"price":tc,"ixic":xc.reindex(tc.index)})
    df["vix"]=vc.reindex(tc.index) if vc is not None else np.nan
    df["vxn"]=vnc.reindex(tc.index) if vnc is not None else np.nan
    df=df.dropna(subset=["price","ixic"]).reset_index()
    df.columns=["date","price","ixic","vix","vxn"]
    return df

# ──────────────────────────────── 차트 ────────────────────────────────
def chart_trend(df,ticker,idx_name="나스닥",cur="$"):
    """상단: 종가·전고점·전저점·평단가 + 나스닥-3% 수직선 (첨부 이미지 상단 재현)"""
    fig=make_subplots(specs=[[{"secondary_y":True}]])
    if "q" in df.columns:
        fig.add_trace(go.Scatter(x=df["date"],y=df["q"],name="전저점",line=dict(width=0.8,color="#e8a5a5"),
            fill="tozeroy",fillcolor="rgba(240,200,200,0.25)"))
    fig.add_trace(go.Scatter(x=df["date"],y=df["peak_nv"],name=f"{ticker} 전고점",line=dict(dash="dot",color="#888",width=1.2)))
    fig.add_trace(go.Scatter(x=df["date"],y=df["price"],name=f"{ticker} 종가",line=dict(color="#c0392b",width=1.6)))
    av=df["avg"].replace(0,np.nan)
    fig.add_trace(go.Scatter(x=df["date"],y=av,name="평단가",line=dict(color="#2980b9",width=1.8,shape="hv")))
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
    fig.update_layout(height=370,margin=dict(l=10,r=70,t=30,b=10),
        legend=dict(orientation="h",y=-0.15),
        title=f"④ 가격 트렌드 · 전고점/전저점 · 평단가 · VIX/VXN · {idx_name} (수직선={idx_name} −3%)",
        yaxis3=dict(title=dict(text=idx_name,font=dict(color="#999")),overlaying="y",side="right",
            position=0.97,showgrid=False,tickfont=dict(color="#999")))
    fig.update_yaxes(title=f"주가({cur})",secondary_y=False)
    fig.update_yaxes(title="VIX / VXN",secondary_y=True,showgrid=False,range=[0,60])
    return fig

def chart_alloc(df,ticker,idx_name="나스닥",cur="$"):
    """하단: 주식평가액/현금 스택 + 종가·평단가 오버레이 + 룰 마커 (이미지 하단 재현)"""
    fig=make_subplots(specs=[[{"secondary_y":True}]])
    fig.add_trace(go.Scatter(x=df["date"],y=df["eq"],name="주식평가액",stackgroup="a",
        line=dict(width=0.5,color="#b7c9a3"),fillcolor="rgba(190,205,160,0.65)"))
    fig.add_trace(go.Scatter(x=df["date"],y=df["cash"],name="현금",stackgroup="a",
        line=dict(width=0.5,color="#e6d84a"),fillcolor="rgba(240,225,80,0.75)"))
    fig.add_trace(go.Scatter(x=df["date"],y=df["price"],name=f"{ticker}종가",line=dict(color="#8b1a1a",width=1.4)),secondary_y=True)
    av=df["avg"].replace(0,np.nan)
    fig.add_trace(go.Scatter(x=df["date"],y=av,name="평단가",line=dict(color="#2980b9",width=1.6,shape="hv")),secondary_y=True)
    ev=df[df["rule"]!=""]
    fig.add_trace(go.Scatter(x=ev["date"],y=ev["price"],mode="markers+text",name="룰 이벤트",
        text=ev["rule"],textposition="top center",textfont=dict(size=9),
        marker=dict(size=7,color="black",symbol="diamond")),secondary_y=True)
    for d in df.loc[df["m3"]==1,"date"]:
        fig.add_vline(x=d,line=dict(color="black",width=1.5,dash="solid"))
    fig.update_layout(height=380,margin=dict(l=10,r=10,t=30,b=10),
        legend=dict(orientation="h",y=-0.15),title=f"① 자산 구성 (주식+현금) · 룰 이벤트 · 수직선={idx_name} −3%")
    fig.update_yaxes(title=f"금액({cur})",secondary_y=False); fig.update_yaxes(title=f"주가({cur})",secondary_y=True,showgrid=False)
    return fig

def chart_perf(df,cur="$"):
    fig=go.Figure()
    fig.add_trace(go.Scatter(x=df["date"],y=df["tot"],name="전략 총자산",line=dict(color="#c0392b",width=1.8)))
    fig.add_trace(go.Scatter(x=df["date"],y=df["bh"],name="존버 B&H",line=dict(color="#2c3e50",width=1.4,dash="dot")))
    fig.update_layout(height=280,margin=dict(l=10,r=10,t=30,b=10),
        legend=dict(orientation="h",y=-0.2),title="③ 총자산 vs 전략 (총자산=주식평가액+현금)")
    return fig

def run_strategy(skey, dates, price, ixic, vix, vxn=None, **params):
    """전략키 하나로 마삼룰 계열/비교전략 계열을 모두 처리하는 공용 진입점.
    반환 df는 어떤 전략이든 'target'(권고 주식비중 0~1) 컬럼을 공통으로 갖는다."""
    if skey in MARSAM_KEYS:
        df = run_engine(dates, price, ixic, skey, **params)
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
 "⚫ 존버 (Buy & Hold)":"bh",
 "📈 200일 이평 추세 (메브 파버)":"ma200",
 "📈 50/200 골든크로스":"cross",
 "🐢 켄트너 채널돌파 (터틀)":"turtle",
 "🚀 절대 모멘텀 (안토나치)":"dualmom",
 "🔄 RSI(2) 평균회귀 (코너스)":"rsi2",
 "📊 변동성 타깃팅 20%":"voltarget",
 "😱 VIX 리스크오프":"vixavoid",
}
MARSAM_KEYS={"full","marsam","bh"}
