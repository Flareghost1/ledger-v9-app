# -*- coding: utf-8 -*-
"""
report.py — 1페이지 md 리포트 생성 (SPEC §6, 우선순위 4)
'이것만 상담창에 붙여넣는다'는 토큰 절약 전략의 산출물.
out/report_YYYYMMDD.md 로 저장하고 문자열도 반환한다.
"""
from datetime import date, datetime
from collections import defaultdict
from pathlib import Path

import prices, cashflow, marsam
import tax_rules as tx
import profile as PROFILE

# 원장으로 계산할 수 없는 고정 규제 마감일 (증여세 신고기한은 gift_tax_summary가 원장에서 직접 계산)
DEADLINES = [
    ("RIA 감면 80% 마감", "2026-07-31", "배우자/장남/차남 AAPL 매도 → 양도세 80% 감면"),
]

def _dday(target, today):
    d = (datetime.strptime(target, "%Y-%m-%d").date() - today).days
    return d

def build(ledger, owner="본인", today=None):
    today = today or date.today()
    all_owners = owner is None          # None = 전체 소유자
    owner_label = "전체" if all_owners else owner
    fx = prices.fx_usdkrw()
    pos = ledger.positions_list(owner)   # positions_list(None) → 전체
    # 실시간 평가
    for p in pos:
        v, cp, ok = prices.value_position(p, fx)
        p["_v"] = v; p["_cp"] = cp; p["_live"] = ok
    total_eq = sum(p["_v"] for p in pos)
    cash_krw = sum(c["amount"] * (fx if c["ccy"] == "USD" else 1) for c in ledger.cash_list(owner))
    total = total_eq + cash_krw

    by_class = defaultdict(float)
    for p in pos:
        by_class[p["asset_class"]] += p["_v"]
    by_class["CASH"] += cash_krw

    ms = marsam.state()
    nq = prices.index_snapshot("^IXIC")
    taxsum = tx.summary(ledger, today)
    cf = cashflow.project(pos, fx, lambda p: p["_v"])

    L = []
    L.append(f"# 자산 리포트 {today.isoformat()} ({owner_label})")
    # 긴급
    L.append("\n## 🔴 긴급 (마감 임박)")
    urg = []
    for name, tgt, desc in DEADLINES:
        dd = _dday(tgt, today)
        if dd >= 0:
            urg.append(f"- {name} **D-{dd}** ({tgt}) — {desc}")
    for w in taxsum["carryover"]:
        diff_txt = f" · 지금 팔면 세금 ₩{w['tax_diff']:,.0f} 더 냄" if w.get("tax_diff") else ""
        urg.append(f"- 이월과세: {w['owner']} {w['asset_id']} 만료 {w['expiry']} (D-{w['days_left']}){diff_txt}")
    for g in taxsum["gift_tax"]:
        if 0 <= g["days_left"] <= 60:
            urg.append(f"- 증여세 신고: {g['recipient']} 기한 {g['filing_deadline']} (D-{g['days_left']}) · 예상세액 ₩{g['tax_due_net']:,.0f}")
    # v8: 기한 D-14 이내 OPEN 액션아이템도 긴급에 포함
    try:
        import action_items as AI
        for it in AI.load_items():
            if it.get("status") != "OPEN" or not it.get("due_date"):
                continue
            dd = _dday(it["due_date"], today)
            if 0 <= dd <= 14:
                urg.append(f"- 액션아이템: {it['title']} (D-{dd})")
    except Exception:
        pass
    L.append("\n".join(urg) if urg else "- 없음")

    # 시장 스냅샷
    L.append("\n## 시장 스냅샷")
    nqv = f"{nq['value']:,.0f}" if nq["value"] else "-"
    nqc = f"{nq['change']:+.2%}" if nq["change"] is not None else "-"
    L.append(f"| 지표 | 값 | 전일비 |\n|---|---|---|\n| 나스닥 | {nqv} | {nqc} |\n| USD/KRW | {fx:,.1f} | - |")

    # 마삼룰
    L.append("\n## 마삼룰")
    stage_txt = f" · 말뚝 {ms['stage']}단계 권역" if ms.get("stage") is not None else ""
    ddtxt = f"NVDA 전고점 대비 {ms['anchor_drawdown']:+.1%}{stage_txt}" if ms.get("anchor_drawdown") is not None else ""
    L.append(f"{ms['detail']}\n{ddtxt}")

    # 자산 요약
    L.append("\n## 자산 요약")
    L.append(f"총자산 **₩{total:,.0f}** (주식평가 ₩{total_eq:,.0f} + 현금 ₩{cash_krw:,.0f})")
    L.append("\n| 자산군 | 평가액 | 비중 |\n|---|---|---|")
    for cls, v in sorted(by_class.items(), key=lambda x: -x[1]):
        if abs(v) < 1: continue
        L.append(f"| {cls} | ₩{v:,.0f} | {v/total:.1%} |")

    # 현금흐름
    L.append("\n## 현금흐름 (실시간 추정)")
    L.append(f"연 세전 ₩{cf['annual_gross']:,.0f} / 세후 ₩{cf['annual_net']:,.0f} / 월평균(세후) ₩{cf['annual_net']/12:,.0f}")

    # 경고
    L.append("\n## ⚠️ 경고")
    fi = taxsum["fin_income"]
    warns = []
    warns.append(f"- 이월과세 만료 전 매도 시도: {'있음 🔴' if taxsum['carryover'] else '없음'}")
    warns.append(f"- RIA 인출금지 위반: {'있음 ⛔' if taxsum['ria']['violations'] else '없음'}")
    warns.append(f"- 금융소득 누적: ₩{fi['total']:,.0f} / ₩{fi['threshold']:,.0f} ({fi['ratio']:.0%}){' ⚠️초과' if fi['over'] else ''}")
    cg = taxsum["capgains"]
    warns.append(f"- 해외양도세(당해 실현): 실현손익 ₩{cg['realized_pnl']:,.0f} → 예상세액 ₩{cg['tax']:,.0f}")
    L.append("\n".join(warns))

    # 증여세 (10년 합산)
    gt = taxsum["gift_tax"]
    if gt:
        L.append("\n## 증여세 (10년 합산)")
        L.append("| 수증자 | 공제구분 | 누적증여 | 과세표준 | 예상세액 | 신고기한 |\n|---|---|---|---|---|---|")
        for g in gt:
            dtxt = "완료" if g["days_left"] < 0 else f"D-{g['days_left']}"
            est = " ⚠️환율추정" if g["has_estimate"] else ""
            L.append(f"| {g['recipient']} | {g['minor']} | ₩{g['cumulative']:,.0f} | ₩{g['taxable']:,.0f} "
                     f"| ₩{g['tax_due_net']:,.0f}{est} | {g['filing_deadline']} ({dtxt}) |")

    # 대사
    L.append("\n## 대사 (Reconciliation) — 증권사 앱과 대조 필요")
    for c in ledger.cash_list(owner):
        L.append(f"- {c['account']} {c['ccy']}: 원장 {c['amount']:,.0f} vs 실제 ? ")

    # 이번 주 체결
    L.append("\n## 최근 체결 (마지막 8건)")
    L.append("| 날짜 | 종목 | 유형 | 수량 | 단가 | thesis |\n|---|---|---|---|---|---|")
    recent = sorted([t for t in ledger.txns if all_owners or t["owner"] == owner],
                    key=lambda t: (t["date"], t["txn_id"]))[-8:]
    for t in recent:
        L.append(f"| {t['date']} | {t['asset_id']} | {t['type']} | {t['qty']} | {t['price']} | {(t['note'] or '')[:30]} |")

    return "\n".join(L)

def save(ledger, owner="본인", today=None):
    today = today or date.today()
    md = build(ledger, owner, today)
    out = PROFILE.out_dir()
    out.mkdir(exist_ok=True, parents=True)
    path = out / f"report_{today.strftime('%Y%m%d')}.md"
    path.write_text(md, encoding="utf-8")
    return path, md

if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from ledger import Ledger
    p, md = save(Ledger())
    print(md)
    print("\n저장:", p)
