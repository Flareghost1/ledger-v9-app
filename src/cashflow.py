# -*- coding: utf-8 -*-
"""
cashflow.py — 배당·쿠폰 예상 현금흐름 (SPEC §src, 우선순위 6)
원장 포지션 + 실시간 평가액을 바탕으로 연간/월별 현금흐름을 추정한다.
분배율·지급월은 아래 INCOME_TABLE(자산별)에 박아둔다. 상장 인컴상품은
'실시간 평가액 × 분배율', 개별주식은 '보유수량 × 주당배당 × 환율'로 계산.
"""
import numpy as np

# asset_id -> dict(kind, rate 또는 dps, months[list], tax_exempt)
#   kind='pct'  → 연현금흐름 = 실시간평가액 × rate
#   kind='dps'  → 연현금흐름 = 수량 × dps(USD) × fx
#   kind='face' → 연현금흐름 = 취득원가(원) × rate  (채권 표면/쿠폰)
INCOME_TABLE = {
    "AAPL":       dict(kind="dps", dps=1.04, months=[2,5,8,11], tax_exempt=False, label="AAPL 배당"),
    "GOOG":       dict(kind="dps", dps=1.06, months=[3,6,9,12], tax_exempt=False, label="GOOG 배당"),
    "MSFT":       dict(kind="dps", dps=3.64, months=[3,6,9,12], tax_exempt=False, label="MSFT 배당"),
    "494300.KS":  dict(kind="pct", rate=0.18, months=list(range(1,13)), tax_exempt=False, label="나스닥100 커버드콜"),
    "483280.KS":  dict(kind="pct", rate=0.15, months=list(range(1,13)), tax_exempt=False, label="AI테크 커버드콜"),
    "088980.KS":  dict(kind="pct", rate=0.065, months=[2,8], tax_exempt=False, label="맥쿼리인프라"),
    "BOND_KR.국고채015003609": dict(kind="face", rate=0.015, months=[3,9], tax_exempt=False, label="국고채 이표"),
    "BOND_FX.브라질2037": dict(kind="face", rate=0.10, months=[1,7], tax_exempt=True, label="브라질2037 쿠폰"),
    "BOND_FX.브라질2035신규": dict(kind="face", rate=0.10, months=[1,7], tax_exempt=True, label="브라질2035 쿠폰"),
    "BOND_FX.브라질2033": dict(kind="face", rate=0.10, months=[1,7], tax_exempt=True, label="브라질2033 쿠폰"),
    "BOND_FX.브라질2031": dict(kind="face", rate=0.10, months=[1,7], tax_exempt=True, label="브라질2031 쿠폰"),
    "BOND_FX.브라질2029": dict(kind="face", rate=0.10, months=[1,7], tax_exempt=True, label="브라질2029 쿠폰"),
    "BOND_FX.브라질2035기존": dict(kind="face", rate=0.10, months=[1,7], tax_exempt=True, label="브라질2035기존 쿠폰"),
    "ELS.교보ELB12532": dict(kind="face", rate=0.04, months=[], tax_exempt=False, label="교보 ELB(만기)"),
}
DIV_TAX = 0.154

def project(positions, fx, value_fn):
    """포지션 리스트 → 현금흐름 항목/월별/연간 요약.
    value_fn(p)=평가액(원) 을 주입받아 실시간 평가액 기준으로 계산."""
    rows = []
    for p in positions:
        info = INCOME_TABLE.get(p["asset_id"])
        if not info:
            continue
        if info["kind"] == "dps":
            annual = p["qty"] * info["dps"] * fx
            basis = f"{p['qty']:.0f}주 × ${info['dps']}/주 × {fx:,.0f}"
        elif info["kind"] == "pct":
            v = value_fn(p)
            annual = v * info["rate"]
            basis = f"평가액 ₩{v:,.0f} × {info['rate']:.1%}"
        else:  # face
            annual = p["cost_krw"] * info["rate"]
            basis = f"원금 ₩{p['cost_krw']:,.0f} × {info['rate']:.1%}"
        rows.append(dict(asset_id=p["asset_id"], label=info["label"], annual=annual,
                         months=info["months"], tax_exempt=info["tax_exempt"], basis=basis))
    monthly = np.zeros(12)
    for r in rows:
        if r["months"]:
            per = r["annual"] / len(r["months"])
            for m in r["months"]:
                monthly[m-1] += per
    annual_gross = sum(r["annual"] for r in rows)
    annual_net = sum(r["annual"] * (1 if r["tax_exempt"] else (1-DIV_TAX)) for r in rows)
    lump = sum(r["annual"] for r in rows if not r["months"])
    return dict(rows=rows, monthly=monthly, annual_gross=annual_gross,
                annual_net=annual_net, lump=lump, div_tax=DIV_TAX)
