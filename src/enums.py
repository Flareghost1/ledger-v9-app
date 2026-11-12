# -*- coding: utf-8 -*-
"""
enums.py — asset_class / type 의 영문·한글 별칭 계층.
원장을 나중에 한글 표준명으로 바꿔도(예: US_STOCK→해외주식, BUY→매수) 코드가 그대로
동작하도록, 어떤 표기가 들어오든 내부 표준(영문 대문자 코드)으로 정규화한다.
"""

# ── asset_class ──
ASSET_CLASS_KO = {
    "US_STOCK": "해외주식", "KR_STOCK": "국내주식", "KR_ETF": "국내ETF",
    "BOND_KR": "국내채권", "BOND_FX": "외화채권", "FUND": "펀드/랩",
    "ELS": "ELS/ELB", "CASH": "현금", "CRYPTO": "가상자산",
    "REALESTATE": "부동산", "PENSION": "연금", "OTHER": "기타",
}
# 역방향 + 별칭(한글·변형) → 표준 영문코드
_ASSET_CLASS_ALIAS = {}
for code, ko in ASSET_CLASS_KO.items():
    _ASSET_CLASS_ALIAS[code.upper()] = code
    _ASSET_CLASS_ALIAS[ko] = code
_ASSET_CLASS_ALIAS.update({
    "해외주식": "US_STOCK", "미국주식": "US_STOCK",
    "국내주식": "KR_STOCK", "한국주식": "KR_STOCK",
    "국내ETF": "KR_ETF", "ETF": "KR_ETF",
    "국내채권": "BOND_KR", "외화채권": "BOND_FX", "브라질채권": "BOND_FX",
    "펀드": "FUND", "랩": "FUND", "펀드/랩": "FUND",
    "ELS": "ELS", "ELB": "ELS", "ELS/ELB": "ELS",
    "현금": "CASH", "예수금": "CASH",
    "가상자산": "CRYPTO", "코인": "CRYPTO",
    "부동산": "REALESTATE", "연금": "PENSION", "기타": "OTHER",
})

# ── type ──
TYPE_KO = {
    "OPEN_POS": "기초포지션", "OPEN_CASH": "기초현금",
    "BUY": "매수", "SELL": "매도", "DEPOSIT": "입금", "WITHDRAW": "출금",
    "TRANSFER_OUT": "대체출고", "TRANSFER_IN": "대체입고",
    "GIFT_OUT": "증여출", "GIFT_IN": "증여입",
    "DIVIDEND": "배당", "INTEREST": "이자", "FEE": "수수료", "TAX": "세금",
    "FX": "환전", "SPLIT": "액면분할", "REVALUE": "평가갱신",
    "COUPON": "채권쿠폰", "BALANCE": "잔고확정", "RP_BUY": "RP매수", "RP_SELL": "RP매도",
    "FX_BUY": "외화매수", "FX_SELL": "외화매도", "CORP_ACTION": "기업행위",
    "SUBSCRIBE": "청약",
}
_TYPE_ALIAS = {}
for code, ko in TYPE_KO.items():
    _TYPE_ALIAS[code.upper()] = code
    _TYPE_ALIAS[ko] = code
_TYPE_ALIAS.update({
    "기초포지션": "OPEN_POS", "개시포지션": "OPEN_POS",
    "기초현금": "OPEN_CASH", "개시현금": "OPEN_CASH",
    "매수": "BUY", "매도": "SELL", "입금": "DEPOSIT", "출금": "WITHDRAW",
    "대체출고": "TRANSFER_OUT", "대체입고": "TRANSFER_IN",
    "증여출": "GIFT_OUT", "증여입": "GIFT_IN", "증여": "GIFT_IN",
    "배당": "DIVIDEND", "이자": "INTEREST", "수수료": "FEE", "세금": "TAX",
    "환전": "FX", "액면분할": "SPLIT", "분할": "SPLIT", "평가갱신": "REVALUE", "재평가": "REVALUE",
    "채권쿠폰": "COUPON", "쿠폰": "COUPON", "이표": "COUPON",
    "잔고확정": "BALANCE", "잔고": "BALANCE",
    "RP매수": "RP_BUY", "RP매도": "RP_SELL",
    "외화매수": "FX_BUY", "외화매도": "FX_SELL",
    "기업행위": "CORP_ACTION", "합병": "CORP_ACTION",
    "청약": "SUBSCRIBE",
})

# ── 잔고(현금) 계산에서 무시하는 타입: 같은 통화 안에서의 '상품' 전환(예수금↔RP)이며,
#    두 하위풀 모두 BALANCE 행에 최종 수치가 별도로 확정 기록되므로 무시해도 이중계상이 안 난다.
#    FX_BUY/FX_SELL은 '통화 자체'가 바뀌는 진짜 현금이동이라 여기 포함하면 안 된다
#    (신한008-11 USD 잔고가 부풀려지는 사고로 확인됨 — ledger.py에서 실제 환전으로 처리).
CASH_NOOP_TYPES = {"RP_BUY", "RP_SELL"}

def norm_class(v):
    """asset_class 표기를 표준 영문코드로 정규화. 미지원이면 원문 대문자 반환."""
    if v is None:
        return ""
    return _ASSET_CLASS_ALIAS.get(str(v).strip(), _ASSET_CLASS_ALIAS.get(str(v).strip().upper(), str(v).strip().upper()))

def norm_type(v):
    """type 표기를 표준 영문코드로 정규화. 미지원이면 원문 대문자 반환."""
    if v is None:
        return ""
    return _TYPE_ALIAS.get(str(v).strip(), _TYPE_ALIAS.get(str(v).strip().upper(), str(v).strip().upper()))

def class_ko(code):
    return ASSET_CLASS_KO.get(code, code)

def type_ko(code):
    return TYPE_KO.get(code, code)
