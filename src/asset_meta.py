# -*- coding: utf-8 -*-
"""
자산 메타데이터: 명세서 종목명 → (asset_id, name_kr, asset_class, price_source, ccy)
price_source: 'yfinance:<티커>' | 'manual'(수동 평가) | 'face_value'(채권 액면)
여기 없는 종목은 manual(원장에 적힌 마지막 평가액 사용)로 처리된다.
"""

# asset_class 코드 (SPEC §1.2)
US_STOCK, KR_STOCK, KR_ETF = "US_STOCK", "KR_STOCK", "KR_ETF"
BOND_KR, BOND_FX, FUND, ELS = "BOND_KR", "BOND_FX", "FUND", "ELS"
CASH, CRYPTO, REALESTATE, PENSION, OTHER = "CASH", "CRYPTO", "REALESTATE", "PENSION", "OTHER"

# 명세서 표기(부분일치 키) → 메타
NAME_META = {
    # 해외주식 (본인)
    "애플 AAPL":              ("AAPL",  "애플",           US_STOCK, "yfinance:AAPL", "USD"),
    "알파벳 GOOG":            ("GOOG",  "알파벳",         US_STOCK, "yfinance:GOOG", "USD"),
    "마이크로소프트 MSFT":    ("MSFT",  "마이크로소프트", US_STOCK, "yfinance:MSFT", "USD"),
    "ESPP 잔여":              ("AAPL",  "애플 ESPP",      US_STOCK, "yfinance:AAPL", "USD"),
    "엔비디아 NVDA":          ("NVDA",  "엔비디아",       US_STOCK, "yfinance:NVDA", "USD"),
    "Cheniere Energy LNG":    ("LNG",   "셰니에르에너지", US_STOCK, "yfinance:LNG",  "USD"),
    "ExxonMobil XOM":         ("XOM",   "엑슨모빌",       US_STOCK, "yfinance:XOM",  "USD"),
    "ConocoPhillips COP":     ("COP",   "코노코필립스",   US_STOCK, "yfinance:COP",  "USD"),
    # 국내주식·ETF (본인)
    "하이비전시스템":         ("126700.KQ", "하이비전시스템", KR_STOCK, "yfinance:126700.KQ", "KRW"),
    "KODEX Top5PlusTR":       ("315930.KS", "KODEX Top5PlusTR", KR_ETF, "yfinance:315930.KS", "KRW"),
    # 금융상품 (상장 = 시세추적)
    "맥쿼리인프라":           ("088980.KS", "맥쿼리인프라", KR_ETF, "yfinance:088980.KS", "KRW"),
    "KODEX 미국AI테크TOP10 타겟커버드콜": ("483280.KS", "KODEX 미국AI테크TOP10 타겟커버드콜", KR_ETF, "yfinance:483280.KS", "KRW"),
    "KODEX 미국나스닥100 데일리커버드콜OTM": ("494300.KS", "KODEX 미국나스닥100 데일리커버드콜OTM", KR_ETF, "yfinance:494300.KS", "KRW"),
    # 자녀 운용 (증여·자녀 시트)
    "KODEX 미국나스닥100":    ("379810.KS", "KODEX 미국나스닥100", KR_ETF, "yfinance:379810.KS", "KRW"),
    "SK하이닉스":             ("000660.KS", "SK하이닉스", KR_STOCK, "yfinance:000660.KS", "KRW"),
    "TIGER 미국필라델피아반도체나스닥": ("381180.KS", "TIGER 미국필라델피아반도체나스닥", KR_ETF, "yfinance:381180.KS", "KRW"),
    "TIGER 글로벌자율주행":   ("394660.KS", "TIGER 글로벌자율주행&전기차SOLACTIVE", KR_ETF, "yfinance:394660.KS", "KRW"),
    "두산":                   ("000150.KS", "두산", KR_STOCK, "yfinance:000150.KS", "KRW"),
    "삼성전자":               ("005930.KS", "삼성전자", KR_STOCK, "yfinance:005930.KS", "KRW"),
    "QQQ":                    ("QQQ",  "인베스코 QQQ", US_STOCK, "yfinance:QQQ",  "USD"),
    "SCHD":                   ("SCHD", "슈왑 배당 SCHD", US_STOCK, "yfinance:SCHD", "USD"),
    "DIS":                    ("DIS",  "월트디즈니", US_STOCK, "yfinance:DIS", "USD"),
    "PLTR":                   ("PLTR", "팔란티어", US_STOCK, "yfinance:PLTR", "USD"),
    "NVDA (NVIDIA)":          ("NVDA", "엔비디아", US_STOCK, "yfinance:NVDA", "USD"),
    "TSLA":                   ("TSLA", "테슬라", US_STOCK, "yfinance:TSLA", "USD"),
    # 채권 (액면·수동)
    "경기지역개발채권":       ("BOND_KR.경기지역개발채권2211", "경기지역개발채권 22-11", BOND_KR, "manual", "KRW"),
    "국고채 01500-3609":      ("BOND_KR.국고채015003609", "국고채 01500-3609(16-6)", BOND_KR, "manual", "KRW"),
    "브라질국채 2035 (기존)": ("BOND_FX.브라질2035기존", "브라질국채 2035(기존)", BOND_FX, "manual", "KRW"),
    "브라질국채 2037 (신규)": ("BOND_FX.브라질2037", "브라질국채 2037(신규)", BOND_FX, "manual", "KRW"),
    "브라질국채 2035 (신규)": ("BOND_FX.브라질2035신규", "브라질국채 2035(신규)", BOND_FX, "manual", "KRW"),
    "브라질국채 2033 (신규)": ("BOND_FX.브라질2033", "브라질국채 2033(신규)", BOND_FX, "manual", "KRW"),
    "브라질국채 2031 (신규)": ("BOND_FX.브라질2031", "브라질국채 2031(신규)", BOND_FX, "manual", "KRW"),
    "브라질국채 2029 (신규)": ("BOND_FX.브라질2029", "브라질국채 2029(신규)", BOND_FX, "manual", "KRW"),
    # 금융상품 (비상장 = 수동)
    "교보증권 ELB":           ("ELS.교보ELB12532", "교보증권 ELB 12532", ELS, "manual", "KRW"),
    "AO 피델리티":            ("FUND.AO피델리티e랩", "AO 피델리티 미국테크 e랩", FUND, "manual", "KRW"),
    "공모ELS":                ("ELS.공모ELS27683", "공모ELS 27683호", ELS, "manual", "KRW"),
    "A1 씨스퀘어":            ("FUND.A1씨스퀘어e랩", "A1 씨스퀘어 e랩", FUND, "manual", "KRW"),
    # 연금
    "퇴직연금 DC":            ("PENSION.교보DC", "교보 퇴직연금 DC", PENSION, "manual", "KRW"),
    "연금저축보험":           ("PENSION.삼성연금저축", "삼성 연금저축보험", PENSION, "manual", "KRW"),
    "IRP 합계":               ("PENSION.IRP", "신한/교보 IRP", PENSION, "manual", "KRW"),
    # 실물
    "황금동":                 ("REALESTATE.황금동8762", "황금동 876-2", REALESTATE, "manual", "KRW"),
    "BTC/XRP/ETH":            ("CRYPTO.BTCXRPETH", "가상자산(BTC/XRP/ETH)", CRYPTO, "manual", "KRW"),
    "보유차량":               ("OTHER.차량", "보유차량(Tesla 등)", OTHER, "manual", "KRW"),
    "입출금잔액":             ("OTHER.포인트", "입출금잔액·포인트", OTHER, "manual", "KRW"),
}

def match_meta(name):
    """명세서 종목명(부분일치)으로 메타 조회. 없으면 None."""
    if not name:
        return None
    for key, meta in NAME_META.items():
        if key in name:
            return meta
    return None
