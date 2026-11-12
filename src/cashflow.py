# -*- coding: utf-8 -*-
"""
cashflow.py — 배당·쿠폰 예상 현금흐름 (SPEC §src, 우선순위 6)

정확도 우선 설계: 예상치는 실제 공시/broker 자료로 확인한 값을 아래 INCOME_TABLE에
하드코딩해서 만든다(원장 이력 자동학습 방식은 지급 이력이 몇 건 안 쌓인 종목에서
부정확했음 — 2026-09-28 결정). 대신 원장에 실제로 찍힌 지급 이력(income_history)과
매번 대조해서 검증하고, 차이가 크면 alerts로 하이라이트한다:
  - 🆕 신규종목: 원장엔 실제 지급 기록이 있는데 이 표에 없는 자산 → 확인 후 표에 추가 필요
  - ❌ 누락: 표에 있는 지급월이 지났는데 원장에 매칭되는 실제 지급 기록이 없음
  - ⚠️ 금액차이: 실제 지급액이 예상(표) 대비 AMOUNT_DIFF_THRESHOLD 이상 차이

새 종목을 발견하면(🆕 알림) 실제 배당률/쿠폰율·지급월을 검색·확인한 뒤 이 표에
직접 추가한다 — 추측치를 자동으로 채워 넣지 않는다.
"""
from datetime import date, timedelta

DIV_TAX = 0.154
AMOUNT_DIFF_THRESHOLD = 0.20  # 이 이상 차이나면 ⚠️ 금액차이로 하이라이트

# asset_id -> dict(kind, ..., months[list], tax_exempt, label)
#   kind='dps'  → 연현금흐름 = 수량 × dps × (USD면 환율, KRW면 1)
#   kind='pct'  → 연현금흐름 = 실시간평가액 × rate
#   kind='face' → 연현금흐름 = 원화 취득원가 × rate  (채권 표면금리/쿠폰)
# 확인일 2026-09-28, 출처는 각 항목 note 참고.
INCOME_TABLE = {
    "AAPL": dict(kind="dps", dps=1.08, months=[2, 5, 8, 11], tax_exempt=False,
                 label="AAPL 배당", note="분기 $0.27 — stockanalysis.com 2026-08"),
    "GOOG": dict(kind="dps", dps=0.88, months=[3, 6, 9, 12], tax_exempt=False,
                 label="GOOG 배당", note="분기 $0.22(2026-04 인상) — stockanalysis.com"),
    "MSFT": dict(kind="dps", dps=3.64, months=[3, 6, 9, 12], tax_exempt=False,
                 label="MSFT 배당", note="분기 $0.91 — 2026-12 지급분부터 $0.98로 인상 예정(자동 금액차이 감지됨)"),
    "NVDA": dict(kind="dps", dps=0.04, months=[1, 4, 7, 10], tax_exempt=False,
                 label="NVDA 배당", note="분기 $0.01(2024-06 10:1 액면분할 반영) — 실제 지급액 검증 후 정정 2026-09-28"),
    "COP": dict(kind="dps", dps=3.36, months=[3, 6, 9, 12], tax_exempt=False,
                label="COP 배당", note="분기 $0.84 — ConocoPhillips IR"),
    "XOM": dict(kind="dps", dps=4.12, months=[3, 6, 9, 12], tax_exempt=False,
                label="XOM 배당", note="분기 $1.03 — ExxonMobil IR"),
    "LNG": dict(kind="dps", dps=2.22, months=[2, 5, 8, 11], tax_exempt=False,
                label="LNG 배당", note="분기 $0.555 — Cheniere 8-K"),
    "DIS": dict(kind="dps", dps=1.50, months=[1, 7], tax_exempt=False,
                label="DIS 배당", note="반기 $0.75×2(분기 아님) — stockanalysis.com"),
    "088980.KS": dict(kind="dps", dps=680, months=[2, 8], tax_exempt=False,
                      label="맥쿼리인프라 분배금", note="반기 ₩300+₩380 — MKIF 공식 투자자정보"),
    "494300.KS": dict(kind="pct", rate=0.168, months=list(range(1, 13)), tax_exempt=False,
                      label="KODEX 나스닥100데일리커버드콜OTM 분배금",
                      note="목표 연 16.8%, 옵션프리미엄 연동이라 변동 — FunETF, 매월 재검증 필요"),
    "483280.KS": dict(kind="pct", rate=0.1464, months=list(range(1, 13)), tax_exempt=False,
                      label="KODEX AI테크TOP10+15%프리미엄 분배금",
                      note="목표 연 14.64% — 삼성자산운용, 매월 재검증 필요"),
    "BOND_KR.국고채015003609": dict(kind="face", rate=0.015, months=[3, 9], tax_exempt=False,
                                   label="국고채 이표", note="표면금리 1.5%, 만기 2036-09-10 — GoInsider"),
    "BOND_FX.브라질2037": dict(kind="face", rate=0.10, months=[1, 7], tax_exempt=True, label="브라질2037 쿠폰"),
    "BOND_FX.브라질2035신규": dict(kind="face", rate=0.10, months=[1, 7], tax_exempt=True, label="브라질2035 쿠폰"),
    "BOND_FX.브라질2033": dict(kind="face", rate=0.10, months=[1, 7], tax_exempt=True, label="브라질2033 쿠폰"),
    "BOND_FX.브라질2031": dict(kind="face", rate=0.10, months=[1, 7], tax_exempt=True, label="브라질2031 쿠폰"),
    "BOND_FX.브라질2029": dict(kind="face", rate=0.10, months=[1, 7], tax_exempt=True, label="브라질2029 쿠폰"),
    "BOND_FX.브라질2035기존": dict(kind="face", rate=0.10, months=[1, 7], tax_exempt=True, label="브라질2035기존 쿠폰"),
    "ELS.교보ELB12532": dict(kind="face", rate=0.04, months=[], tax_exempt=False, label="교보 ELB(만기)"),
}
for _k, _v in INCOME_TABLE.items():
    if _v["kind"] in ("face", "pct"):
        _v.setdefault("note", "브라질 국채 표면금리 10% · 반기 · 비과세(한-브라질 조세조약) — 2026-09-28 확인")


def _d(s):
    return date(int(s[:4]), int(s[5:7]), int(s[8:10]))


def _annual_and_basis(plist, info, fx):
    """plist: 같은 asset_id를 가진 포지션들(계좌·소유자 여러 건 가능) — 합산해서 계산한다."""
    if info["kind"] == "dps":
        qty = sum(p["qty"] for p in plist)
        ccy = plist[0]["ccy"]
        mult = fx if ccy == "USD" else 1
        annual = qty * info["dps"] * mult
        unit = f"${info['dps']}" if ccy == "USD" else f"₩{info['dps']:,.0f}"
        basis = f"{qty:.0f}주 × {unit}" + (f" × {mult:,.1f}" if ccy == "USD" else "")
    elif info["kind"] == "pct":
        v = sum(p["_v"] for p in plist)
        annual = v * info["rate"]
        basis = f"평가액 ₩{v:,.0f} × {info['rate']:.1%}"
    else:  # face
        cost = sum(p["cost_krw"] for p in plist)
        annual = cost * info["rate"]
        basis = f"원금 ₩{cost:,.0f} × {info['rate']:.1%}"
    return annual, basis


def _expected_dates(months, today, first_actual, tolerance, lookback_days=365):
    """최근 lookback_days 이내 + '첫 실제 지급일 - 허용오차' 이후에 도래한 지급 예정일(그 달 15일 기준).
    첫 실제 지급보다 한참 전인 주기는 보유 전이었을 가능성이 높아 누락 판정에서 제외한다
    (허용오차만큼만 앞당겨서, 15일 기준일과 실제 지급일이 살짝 어긋나 첫 지급 자체가
    걸러지는 것은 방지한다)."""
    start = max(today - timedelta(days=lookback_days), first_actual - timedelta(days=tolerance))
    out = []
    for yr in (today.year - 1, today.year):
        for m in months:
            try:
                d = date(yr, m, 15)
            except ValueError:
                continue
            if start <= d <= today:
                out.append(d)
    return sorted(out)


def _verify(rows, positions, income_history, today):
    """표 기반 예상(rows) vs 원장 실제(income_history) 대조 → alerts 생성."""
    by_asset = {}
    for i in income_history:
        by_asset.setdefault(i["asset_id"], []).append(i)
    for v in by_asset.values():
        v.sort(key=lambda i: i["date"])

    held_ids = {p["asset_id"] for p in positions}
    alerts = []

    # 🆕 신규종목: 실제 지급 이력은 있는데 표에 없음
    for aid, hist in sorted(by_asset.items()):
        if aid in INCOME_TABLE:
            continue
        last = hist[-1]
        alerts.append(dict(type="신규종목", asset_id=aid,
                           msg=f"🆕 {aid}: 원장에 실제 지급 기록 있음(최근 {last['date']} ₩{last['amount_krw']:,.0f})"
                               f" — 하드코딩 표에 없음, 배당정보 확인 후 추가 필요"))

    # ❌ 누락 / ⚠️ 금액차이: 표에 있고 현재 보유 중인 종목만 대조
    for r in rows:
        aid = r["asset_id"]
        if aid not in held_ids or not r["months"]:
            continue
        hist = by_asset.get(aid)
        if not hist:
            continue  # 실제 지급 이력이 아직 한 건도 없으면(신규 편입 등) 누락 판정 보류
        per_expected = r["annual"] / len(r["months"])
        actual_dates = [(_d(i["date"]), i) for i in hist]
        first_actual = actual_dates[0][0]
        tolerance = max(10, min(45, max(1, 365 // len(r["months"])) // 2))
        used = set()
        for ed in _expected_dates(r["months"], today, first_actual, tolerance):
            cands = [(abs((d - ed).days), idx, i) for idx, (d, i) in enumerate(actual_dates)
                     if idx not in used and abs((d - ed).days) <= tolerance]
            if not cands:
                if (today - ed).days > tolerance:  # 허용오차 이내면 아직 지급 대기중일 뿐 — 누락 아님
                    alerts.append(dict(type="누락", asset_id=aid,
                                       msg=f"❌ {r['label']}: {ed.strftime('%Y-%m')}월 지급 예정이었으나 "
                                           f"원장에 매칭되는 실제 지급 기록 없음(예상 ₩{per_expected:,.0f})"))
                continue
            cands.sort(key=lambda x: x[0])
            _, idx, actual = cands[0]
            used.add(idx)
            diff = actual["amount_krw"] - per_expected
            if per_expected and abs(diff) / per_expected > AMOUNT_DIFF_THRESHOLD:
                alerts.append(dict(type="금액차이", asset_id=aid,
                                   msg=f"⚠️ {r['label']}: {actual['date']} 실제 ₩{actual['amount_krw']:,.0f} "
                                       f"vs 예상 ₩{per_expected:,.0f} ({diff/per_expected:+.0%})"))
    return alerts


def project(positions, income_history, fx, today=None):
    """positions: ctx.pos_f 등 (evaluated: _v, cost_krw, ccy 포함) 포지션 리스트 — 같은 asset_id가
    여러 계좌/소유자에 걸쳐 있으면 합산해서 예상치를 만든다.
    income_history: 그 소유자·필터 범위의 ctx.L.income (연도 제한 없이 전체 — 검증에 필요).
    fx: USD/KRW 환율.
    반환: rows(자산별 예상 — 하드코딩 표 기준), monthly(1~12월 배분),
          annual_gross/net, div_tax, alerts(신규종목/누락/금액차이)."""
    today = today or date.today()
    by_asset_pos = {}
    for p in positions:
        if p["asset_id"] in INCOME_TABLE:
            by_asset_pos.setdefault(p["asset_id"], []).append(p)

    rows = []
    for aid, plist in by_asset_pos.items():
        info = INCOME_TABLE[aid]
        annual, basis = _annual_and_basis(plist, info, fx)
        rows.append(dict(asset_id=aid, label=info["label"], annual=annual,
                         months=info["months"], tax_exempt=info["tax_exempt"],
                         basis=basis + f" ({info.get('note', '')})"))

    monthly = [0.0] * 12
    for r in rows:
        if r["months"]:
            per = r["annual"] / len(r["months"])
            for m in r["months"]:
                monthly[m - 1] += per
    annual_gross = sum(r["annual"] for r in rows)
    annual_net = sum(r["annual"] * (1 if r["tax_exempt"] else (1 - DIV_TAX)) for r in rows)
    alerts = _verify(rows, positions, income_history, today)
    return dict(rows=rows, monthly=monthly, annual_gross=annual_gross,
                annual_net=annual_net, div_tax=DIV_TAX, alerts=alerts)
