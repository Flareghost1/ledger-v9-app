# -*- coding: utf-8 -*-
"""
build_masters.py — 원장(transactions.csv)에 등장하는 asset_id/account로부터
assets.csv / accounts.csv 마스터를 생성한다.
yfinance 티커는 longName을 조회해 로그로 남긴다(코드 오입력 검증, SPEC 요구).
"""
import sys, csv
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
from ledger import load_csv
from asset_meta import match_meta   # 종목명→메타 매핑(부분일치)
from enums import norm_class

BASE = Path(__file__).resolve().parent

# asset_id 직접 → (name_kr, price_source, ccy, tax_exempt) 보강 테이블
DIRECT = {
    "CASH.USD": ("달러 예수금", "manual", "USD", "N"),
    "CASH.KRW": ("원화 예수금", "manual", "KRW", "N"),
    "AAPL": ("애플", "yfinance:AAPL", "USD", "N"),
    "GOOG": ("알파벳", "yfinance:GOOG", "USD", "N"),
    "MSFT": ("마이크로소프트", "yfinance:MSFT", "USD", "N"),
    "NVDA": ("엔비디아", "yfinance:NVDA", "USD", "N"),
    "LNG": ("셰니에르에너지", "yfinance:LNG", "USD", "N"),
    "XOM": ("엑슨모빌", "yfinance:XOM", "USD", "N"),
    "COP": ("코노코필립스", "yfinance:COP", "USD", "N"),
    "QQQ": ("인베스코 QQQ", "yfinance:QQQ", "USD", "N"),
    "SCHD": ("슈왑 배당 SCHD", "yfinance:SCHD", "USD", "N"),
    "DIS": ("월트디즈니", "yfinance:DIS", "USD", "N"),
    "PLTR": ("팔란티어", "yfinance:PLTR", "USD", "N"),
    "TSLA": ("테슬라", "yfinance:TSLA", "USD", "N"),
    "126700.KQ": ("하이비전시스템", "yfinance:126700.KQ", "KRW", "N"),
    "315930.KS": ("KODEX Top5PlusTR", "yfinance:315930.KS", "KRW", "N"),
    "088980.KS": ("맥쿼리인프라", "yfinance:088980.KS", "KRW", "N"),
    "483280.KS": ("KODEX 미국AI테크TOP10 타겟커버드콜", "yfinance:483280.KS", "KRW", "N"),
    "494300.KS": ("KODEX 미국나스닥100 데일리커버드콜OTM", "yfinance:494300.KS", "KRW", "N"),
    "379810.KS": ("KODEX 미국나스닥100", "yfinance:379810.KS", "KRW", "N"),
    "000660.KS": ("SK하이닉스", "yfinance:000660.KS", "KRW", "N"),
    "394660.KS": ("TIGER 글로벌자율주행&전기차SOLACTIVE", "yfinance:394660.KS", "KRW", "N"),
    "381180.KS": ("TIGER 미국필라델피아반도체나스닥", "yfinance:381180.KS", "KRW", "N"),
    "000150.KS": ("두산", "yfinance:000150.KS", "KRW", "N"),
    "005930.KS": ("삼성전자", "yfinance:005930.KS", "KRW", "N"),
    # 비상장/수동 자산 (asset_id 접두사로 자산군 유추)
}
# 브라질국채 쿠폰 비과세
def _direct_or_infer(aid, acls):
    if aid in DIRECT:
        return DIRECT[aid]
    # 접두사 기반 유추
    name = aid.split(".", 1)[-1] if "." in aid else aid
    tax_exempt = "Y" if aid.startswith("BOND_FX") else "N"
    ccy = "KRW"
    return (name, "manual", ccy, tax_exempt)

def verify_ticker(ps, name_kr):
    """yfinance longName 조회해 로그. (네트워크 필요, 실패해도 진행)"""
    if not ps.startswith("yfinance:"):
        return None
    t = ps.split(":", 1)[1]
    try:
        import yfinance as yf
        info = yf.Ticker(t).info
        ln = info.get("longName") or info.get("shortName")
        return ln
    except Exception as e:
        return f"(조회실패: {e})"

def main(verify=True, data_dir=None):
    if data_dir is None:
        sys.path.insert(0, str(BASE / "src"))
        import profile as PROFILE
        data_dir = PROFILE.data_dir()
    DATA = Path(data_dir)
    txns = load_csv(DATA / "transactions.csv")
    # 자산
    seen = {}
    for t in txns:
        aid = t["asset_id"]; acls = norm_class(t["asset_class"])
        if aid in seen: continue
        name, ps, ccy, tex = _direct_or_infer(aid, acls)
        seen[aid] = dict(asset_id=aid, name_kr=name, asset_class=acls, price_source=ps,
                         ccy=ccy, tax_exempt=tex, div_per_share="", div_months="",
                         maturity="", coupon="")
    # 티커 검증 로그
    if verify:
        print("── yfinance 티커 검증 (longName) ──")
        for aid, a in seen.items():
            if a["price_source"].startswith("yfinance:"):
                ln = verify_ticker(a["price_source"], a["name_kr"])
                flag = "✅" if ln and "실패" not in str(ln) else "⚠️"
                print(f"  {flag} {aid:14} {a['price_source']:22} → {ln}")
    acols = ["asset_id","name_kr","asset_class","price_source","ccy","tax_exempt","div_per_share","div_months","maturity","coupon"]
    with open(DATA/"assets.csv","w",encoding="utf-8-sig",newline="") as f:
        w = csv.DictWriter(f, fieldnames=acols); w.writeheader()
        for a in seen.values(): w.writerow(a)

    # 계좌
    accts = {}
    for t in txns:
        a = t["account"]; owner = t["owner"]; tag = t.get("tag") or ""
        if not a or a in accts: continue
        broker = ("삼성" if a.startswith("삼성") else "신한" if a.startswith("신한") else
                  "E*TRADE" if "TRADE" in a.upper() else "교보" if "교보" in a or a=="교보DC" else
                  "삼성생명" if a=="삼성연금" else "기타")
        atype = ("RIA" if "RIA" in a else "신탁" if "신탁" in a else
                 "연금" if any(k in a for k in ("교보DC","삼성연금","IRP")) else "일반")
        restr = "RIA_NO_WITHDRAW_1Y;KR_STOCK_ONLY" if "RIA" in a else ""
        accts[a] = dict(account=a, owner=owner, broker=broker, account_type=atype, restrictions=restr)
    with open(DATA/"accounts.csv","w",encoding="utf-8-sig",newline="") as f:
        w = csv.DictWriter(f, fieldnames=["account","owner","broker","account_type","restrictions"])
        w.writeheader()
        for a in accts.values(): w.writerow(a)
    print(f"\n자산 {len(seen)}종, 계좌 {len(accts)}개 생성 완료.")

if __name__ == "__main__":
    main(verify="--noverify" not in sys.argv)
