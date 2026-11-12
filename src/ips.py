# -*- coding: utf-8 -*-
"""
ips.py — IPS 준수현황 (v8 명세 §2)
설정(settings.json)의 ips_goals 리스트를 순회하며 목표 대비 진행률을 계산한다.
목표는 개인마다 다르므로 코드에 박지 않는다 — 설정 탭에서 자유롭게 추가/수정.
"""
from datetime import date
from collections import defaultdict


def _goal_asset_class_sum(goal, positions):
    """특정 자산군의 원금(cost_krw) 합산."""
    return sum(p["cost_krw"] for p in positions if p["asset_class"] == goal.get("match"))


def _goal_account_deposit_annual(goal, ledger, year):
    """특정 계좌의 해당 연도 DEPOSIT 누적(원화환산)."""
    from enums import norm_type
    total = 0.0
    for t in ledger.txns:
        if t["account"] != goal.get("match") or norm_type(t["type"]) != "DEPOSIT":
            continue
        if str(t["date"])[:4] != str(year):
            continue
        try:
            total += float(t.get("amount_ccy") or t.get("amount") or 0) * float(t.get("fx") or 1)
        except (ValueError, TypeError):
            continue
    return total


def _goal_position_weight(goal, positions, total_asset):
    """특정 종목의 총자산 대비 비중(%). 전 계좌 합산."""
    v = sum(p.get("_v", p["cost_krw"]) for p in positions if p["asset_id"] == goal.get("match"))
    return (v / total_asset * 100) if total_asset else 0.0


def compliance(ledger, positions, total_asset, settings, fin_full, today=None):
    """ips_goals → [{label, current, target, ratio, unit, status, note}] 진행률 리스트."""
    today = today or date.today()
    out = []
    for g in settings.get("ips_goals", []):
        metric = g.get("metric")
        label = g.get("label") or g.get("match") or metric
        target = g.get("target")
        unit = "원"
        note = ""
        if metric == "asset_class_sum":
            current = _goal_asset_class_sum(g, positions)
        elif metric == "account_deposit_annual":
            current = _goal_account_deposit_annual(g, ledger, today.year)
            target = (g.get("target_by_year") or {}).get(str(today.year))
            note = f"{today.year}년 납입 기준"
            if target is None:
                note = f"{today.year}년 목표 미설정 — 설정 탭에서 연도별 목표 입력"
        elif metric == "position_weight_pct":
            current = _goal_position_weight(g, positions, total_asset)
            unit = "%"
        elif metric == "financial_income_ratio":
            current = fin_full["ytd"]["taxable"]
            target = fin_full["threshold"]
            note = f"연말 예상 ₩{fin_full['est']['taxable']:,.0f}" + (" ⚠️초과 전망" if fin_full["est_over"] else "")
        else:
            continue
        ratio = (current / target) if target else None
        status = "미정" if target is None else ("초과" if ratio > 1 else "진행중")
        # 금융소득은 '초과'가 나쁜 신호(빨강), 나머지는 달성이 좋은 신호
        bad_over = (metric == "financial_income_ratio")
        out.append(dict(id=g.get("id"), label=label, metric=metric, current=current,
                        target=target, ratio=ratio, unit=unit, status=status,
                        bad_over=bad_over, note=note))
    return out


def plan_vs_actual(ledger, cf_monthly, today=None):
    """연초 계획(배당지급월 스케줄 이론치) vs 실적(원장 실수령) 월별 비교.
    계획 = cashflow.project()의 monthly 배열(세전) 재사용 — §2-2 명세.
    실적 = ledger.income의 올해 실수령액을 월별 집계."""
    today = today or date.today()
    actual = [0.0] * 12
    for i in ledger.income:
        d = str(i["date"])[:7]
        if d[:4] != str(today.year):
            continue
        try:
            m = int(d[5:7])
        except ValueError:
            continue
        actual[m - 1] += i["amount_krw"]
    return dict(plan=list(cf_monthly), actual=actual,
                plan_ytd=sum(cf_monthly[:today.month]), actual_ytd=sum(actual[:today.month]))
