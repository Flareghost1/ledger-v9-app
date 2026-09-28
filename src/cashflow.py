# -*- coding: utf-8 -*-
"""
cashflow.py — 배당·쿠폰 예상 현금흐름 (SPEC §src, 우선순위 6)

하드코딩된 배당표(INCOME_TABLE) 대신, 원장에 실제로 찍힌 DIVIDEND/INTEREST/
COUPON 이력에서 직접 학습한다 — 그 (계좌,종목)에 실제 지급된 달(月)들과
가장 최근 지급액을 그대로 앞으로 1년에도 반복된다고 가정해 예상치를 만든다.
그래서 원장에 새 배당·이자가 기록되는 순간부터(다음 새로고침부터, 코드 수정
없이) 예상에 자동 반영되고, 지급 이력이 아직 없는 종목은 예상에서 자동으로
빠진다(수동으로 등록/삭제할 필요가 없다).

한계: 지급 이력이 1건뿐인 종목은 그 1건의 달만으로 '연 1회'라고 가정한다 —
실제 주기(분기·반기 등)를 몰라서 생기는 보수적인 추정이며, 다음 지급이
찍히면 자동으로 정확해진다. 배당락 시점의 보유수량 변화도 반영 못 하고
'가장 최근 지급액'을 그대로 쓴다 — 이 역시 다음 지급이 찍히면 갱신된다.
"""

DIV_TAX = 0.154


def project(positions, income_history):
    """positions: ctx.pos_f 등 (owner,account,asset_id) 단위 포지션 리스트.
    income_history: 그 소유자·필터 범위의 ctx.L.income (account 필드 포함, 전체 기간 — 연도로
    자르면 안 된다. 지급월 패턴을 과거 전체에서 학습해야 하기 때문).
    반환: rows(자산별 예상), monthly(1~12월 배분), annual_gross/net, div_tax."""
    by_key = {}
    for i in income_history:
        by_key.setdefault((i.get("account"), i["asset_id"]), []).append(i)
    for v in by_key.values():
        v.sort(key=lambda i: i["date"])

    rows = []
    seen = set()
    for p in positions:
        key = (p["account"], p["asset_id"])
        hist = by_key.get(key)
        if not hist or key in seen:
            continue
        seen.add(key)
        months = sorted({int(str(i["date"])[5:7]) for i in hist})
        last = hist[-1]
        annual = last["amount_krw"] * len(months)
        rows.append(dict(
            asset_id=p["asset_id"], account=p["account"], label=p["name"],
            annual=annual, months=months, tax_exempt=bool(last["tax_exempt"]),
            basis=f"최근 지급 {last['date']} ₩{last['amount_krw']:,.0f} × 연 {len(months)}회 "
                  f"(지급월 {','.join(f'{mm}월' for mm in months)} · 이력 {len(hist)}건 학습)"))

    monthly = [0.0] * 12
    for r in rows:
        per = r["annual"] / len(r["months"])
        for mm in r["months"]:
            monthly[mm - 1] += per
    annual_gross = sum(r["annual"] for r in rows)
    annual_net = sum(r["annual"] * (1 if r["tax_exempt"] else (1 - DIV_TAX)) for r in rows)
    return dict(rows=rows, monthly=monthly, annual_gross=annual_gross,
                annual_net=annual_net, div_tax=DIV_TAX)
