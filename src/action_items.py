# -*- coding: utf-8 -*-
"""
action_items.py — 액션아이템 트래커 (v8 명세 §1)
data/action_items.csv 는 transactions.csv(거래원장)와 완전히 분리된 별도 원장 —
액션아이템 완료 여부가 거래원장을 오염시키지 않는다.

자동 생성 트리거(check_*)는 대시보드 로드마다 실행해도 안전하도록 idempotent:
같은 source 키로 이미 생성된 항목(OPEN/DONE/DISMISSED 무관)이 있으면 재생성하지 않는다.
"""
import csv
from datetime import date, datetime

import profile as PROFILE

# memo = 사용자가 직접 적는 진행메모(자동생성 detail과 구분). 구버전 CSV에 없어도
# load 시 빈 값으로 채워지므로 하위호환된다.
COLS = ["id", "created_date", "source", "category", "title", "detail",
        "due_date", "status", "completed_date", "linked_txn_id", "notion_page_id", "memo"]

CATEGORIES = ["세금", "현금흐름", "리밸런싱", "IPS준수", "기타"]
STATUSES = ["OPEN", "DONE", "DISMISSED"]


def _path():
    return PROFILE.data_dir() / "action_items.csv"


def _today():
    return date.today().isoformat()


def load_items():
    try:
        with open(_path(), encoding="utf-8-sig") as f:
            items = list(csv.DictReader(f))
    except FileNotFoundError:
        return []
    for it in items:          # 신규 컬럼(memo 등) 하위호환
        for c in COLS:
            it.setdefault(c, "")
    return items


def save_items(items):
    path = _path()
    path.parent.mkdir(exist_ok=True)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        w.writeheader()
        for it in items:
            w.writerow({c: it.get(c, "") for c in COLS})


def add_item(items, source, category, title, detail="", due_date="", linked_txn_id=""):
    """items 리스트에 새 항목 추가(저장은 호출부에서 save_items). 반환: 새 항목."""
    next_id = max((int(it["id"]) for it in items if str(it.get("id", "")).isdigit()), default=0) + 1
    item = dict(id=str(next_id), created_date=_today(), source=source, category=category,
                title=title, detail=detail, due_date=due_date, status="OPEN",
                completed_date="", linked_txn_id=linked_txn_id, notion_page_id="", memo="")
    items.append(item)
    return item


def set_status(items, item_id, status):
    """상태 변경 + DONE이면 completed_date 자동 기록."""
    for it in items:
        if str(it["id"]) == str(item_id):
            it["status"] = status
            it["completed_date"] = _today() if status == "DONE" else ""
            return it
    return None


def _existing_sources(items):
    return {it.get("source", "") for it in items}


# ══════════════ 자동 생성 트리거 (§1-3) ══════════════

def check_dividend_deposits(items, ledger):
    """배당/이자/쿠폰 입금 거래 → '배분처 선택' 액션아이템. 거래 1건당 1회."""
    from enums import norm_type
    seen = _existing_sources(items)
    created = []
    for t in ledger.txns:
        typ = norm_type(t["type"])
        if typ not in ("DIVIDEND", "INTEREST", "COUPON"):
            continue
        src = f"AUTO:DIV:{t['txn_id']}"
        if src in seen:
            continue
        try:
            amt = float(t.get("amount_ccy") or t.get("amount") or 0)
            fx = float(t.get("fx") or 1)
        except (ValueError, TypeError):
            amt, fx = 0, 1
        krw = amt * fx
        created.append(add_item(
            items, src, "현금흐름",
            f"{t['asset_id']} {'배당' if typ=='DIVIDEND' else '이자/쿠폰'} ₩{krw:,.0f} — "
            "실제 입고여부 확인 + 현금 용도 결정(생활비/재투자/ISA)",
            detail=f"{t['date']} {t['owner']} {t['account']} · {t.get('note','')}",
            linked_txn_id=t["txn_id"]))
    return created


def check_carryover_d30(items, ledger, today=None):
    """이월과세 해제 D-30 이내 → 매도 검토 액션아이템."""
    import tax_rules as tx
    today = today or date.today()
    seen = _existing_sources(items)
    created = []
    for w in tx.carryover_warnings(ledger, today):
        if not (0 <= w["days_left"] <= 30):
            continue
        src = f"AUTO:CARRYOVER:{w['owner']}:{w['asset_id']}:{w['expiry']}"
        if src in seen:
            continue
        created.append(add_item(
            items, src, "세금",
            f"{w['owner']} {w['asset_id']} 이월과세 해제 D-{w['days_left']} — 매도 검토 여부 확인",
            detail=w["msg"], due_date=w["expiry"]))
    return created


def check_fin_income_80pct(items, fin_full, today=None):
    """금융소득 누적이 임계값의 80% 도달 → 하반기 배당 재배치 검토. 연 1회."""
    today = today or date.today()
    if fin_full["ratio"] < 0.8:
        return []
    src = f"AUTO:FININCOME80:{today.year}"
    if src in _existing_sources(items):
        return []
    thr = fin_full["threshold"]
    return [add_item(
        items, src, "세금",
        f"금융소득 {thr/10_000:,.0f}만 임계 80% 도달 (누적 ₩{fin_full['ytd']['taxable']:,.0f}) — 하반기 배당 재배치 검토",
        detail=f"연말 예상 과세 금융소득 ₩{fin_full['est']['taxable']:,.0f}")]


def check_gift_deadline_d14(items, ledger, today=None):
    """증여세 신고기한 D-14 이내 → 세무사 확인 액션아이템."""
    import tax_rules as tx
    today = today or date.today()
    seen = _existing_sources(items)
    created = []
    for g in tx.gift_tax_summary(ledger, today):
        if not (0 <= g["days_left"] <= 14):
            continue
        src = f"AUTO:GIFTDL:{g['recipient']}:{g['filing_deadline']}"
        if src in seen:
            continue
        created.append(add_item(
            items, src, "세금",
            f"{g['recipient']} 증여세 신고 D-{g['days_left']} — 세무사 확인",
            detail=f"신고기한 {g['filing_deadline']} · 예상세액 ₩{g['tax_due_net']:,.0f}",
            due_date=g["filing_deadline"]))
    return created


def check_goal_underfunded(items, ledger, ips_goals, today=None):
    """계좌 연납입 목표(account_deposit_annual)가 11월 이후에도 미달이면 연내 완료 알림.
    ISA 전용이 아니라 어떤 계좌 목표든 동작(범용). 목표 미설정 시 스킵."""
    from enums import norm_type
    today = today or date.today()
    if today.month < 11:
        return []
    seen = _existing_sources(items)
    created = []
    for g in ips_goals:
        if g.get("metric") != "account_deposit_annual":
            continue
        target = (g.get("target_by_year") or {}).get(str(today.year))
        if not target:
            continue
        deposited = 0.0
        for t in ledger.txns:
            if t["account"] != g.get("match") or norm_type(t["type"]) != "DEPOSIT":
                continue
            if str(t["date"])[:4] != str(today.year):
                continue
            try:
                deposited += float(t.get("amount_ccy") or t.get("amount") or 0) * float(t.get("fx") or 1)
            except (ValueError, TypeError):
                continue
        if deposited >= target:
            continue
        src = f"AUTO:GOALFUND:{g.get('id')}:{today.year}"
        if src in seen:
            continue
        created.append(add_item(
            items, src, "IPS준수",
            f"{today.year}년 {g.get('label', g.get('match'))} {target/10_000:,.0f}만 중 "
            f"{(target-deposited)/10_000:,.0f}만 미납 — 연내 완료 필요",
            detail=f"목표 ₩{target:,.0f} / 납입 ₩{deposited:,.0f}", due_date=f"{today.year}-12-31"))
    return created


def check_ips_shortfall(items, goals_result, today=None):
    """v9 §11: IPS 목표 미달(또는 나쁜 초과) 항목 → 액션아이템 자동 등록.
    goals_result = ips.compliance() 결과. 목표당 연 1회(idempotent).
    '연초 계획 vs 실적' 그래프를 대체 — 미달이 액션아이템 탭에 통합된다."""
    today = today or date.today()
    seen = _existing_sources(items)
    created = []
    for g in goals_result or []:
        if g.get("target") is None or g.get("ratio") is None:
            continue
        bad = (g["bad_over"] and g["ratio"] > 1) or (not g["bad_over"] and g["ratio"] < 1)
        if not bad:
            continue
        src = f"AUTO:IPS:{g.get('id')}:{today.year}"
        if src in seen:
            continue
        if g["unit"] == "%":
            cur_txt, tgt_txt = f"{g['current']:,.1f}%", f"{g['target']:,.1f}%"
        else:
            cur_txt, tgt_txt = f"₩{g['current']:,.0f}", f"₩{g['target']:,.0f}"
        state = "임계 초과" if g["bad_over"] else "목표 미달"
        created.append(add_item(
            items, src, "IPS준수",
            f"IPS {state}: {g['label']} — 현재 {cur_txt} / 목표 {tgt_txt} ({g['ratio']:.0%})",
            detail=(g.get("note") or "") + " · IPS준수 탭에서 진행률 확인",
            due_date=f"{today.year}-12-31"))
    return created


def run_all_triggers(ledger, fin_full, ips_goals, today=None, goals_result=None):
    """모든 트리거 실행 → 새로 생긴 항목 수 반환. 변경 있을 때만 저장."""
    items = load_items()
    created = []
    created += check_dividend_deposits(items, ledger)
    created += check_carryover_d30(items, ledger, today)
    created += check_fin_income_80pct(items, fin_full, today)
    created += check_gift_deadline_d14(items, ledger, today)
    created += check_goal_underfunded(items, ledger, ips_goals, today)
    created += check_ips_shortfall(items, goals_result, today)
    if created:
        save_items(items)
    return len(created)
