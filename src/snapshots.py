# -*- coding: utf-8 -*-
"""
snapshots.py — 총자산 일별 스냅샷 (v8 명세 §4 기간비교)
앱 실행 시 1일 1회 (date, owner)별 총자산을 asset_snapshots.csv에 append.
비교 시점 값이 없으면 가장 가까운 이전 날짜로 대체하고 '근사치' 라벨을 붙인다.
"""
import csv
from datetime import date, timedelta

import profile as PROFILE

COLS = ["date", "owner", "total_asset_krw", "stock_value", "cash"]
DETAIL_COLS = ["date", "owner", "kind", "key", "value_krw"]

BASES = ["전일", "전주", "전월", "3개월", "반년", "연초", "작년말"]


def _path():
    return PROFILE.data_dir() / "asset_snapshots.csv"


def _detail_path():
    return PROFILE.data_dir() / "asset_snapshots_detail.csv"


def _load():
    try:
        with open(_path(), encoding="utf-8-sig") as f:
            return list(csv.DictReader(f))
    except FileNotFoundError:
        return []


def record_snapshot(owner, total, stock_value, cash, today=None):
    """오늘자 스냅샷 기록. 같은 (date, owner)가 이미 있으면 skip(1일 1회)."""
    today = (today or date.today()).isoformat()
    rows = _load()
    if any(r["date"] == today and r["owner"] == owner for r in rows):
        return False
    path = _path()
    path.parent.mkdir(exist_ok=True)
    exists = path.exists()
    with open(path, "a", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        if not exists:
            w.writeheader()
        w.writerow(dict(date=today, owner=owner, total_asset_krw=f"{total:.0f}",
                        stock_value=f"{stock_value:.0f}", cash=f"{cash:.0f}"))
    return True


def _load_detail():
    try:
        with open(_detail_path(), encoding="utf-8-sig") as f:
            return list(csv.DictReader(f))
    except FileNotFoundError:
        return []


def record_detail(owner, by_class, by_item, today=None):
    """오늘자 자산군·항목별 시가 스냅샷 기록(1일 1회). by_class/by_item: {키: 평가액(원)}."""
    today = (today or date.today()).isoformat()
    rows = _load_detail()
    if any(r["date"] == today and r["owner"] == owner for r in rows):
        return False
    detail_path = _detail_path()
    detail_path.parent.mkdir(exist_ok=True)
    exists = detail_path.exists()
    with open(detail_path, "a", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=DETAIL_COLS)
        if not exists:
            w.writeheader()
        for k, v in by_class.items():
            w.writerow(dict(date=today, owner=owner, kind="class", key=k, value_krw=f"{v:.0f}"))
        for k, v in by_item.items():
            w.writerow(dict(date=today, owner=owner, kind="item", key=k, value_krw=f"{v:.0f}"))
    return True


def series_detail(owner, kind, since_iso=None):
    """owner의 kind('class'|'item')별 일별 시계열. since_iso 이상만.
    반환: [{date, key, value}, ...] (long format)."""
    out = []
    for r in _load_detail():
        if r["owner"] != owner or r["kind"] != kind:
            continue
        if since_iso and r["date"] < since_iso:
            continue
        try:
            out.append(dict(date=r["date"], key=r["key"], value=float(r["value_krw"])))
        except (ValueError, TypeError):
            continue
    return out


def _months_ago(today, n):
    m, y = today.month - n, today.year
    while m <= 0:
        m, y = m + 12, y - 1
    day = min(today.day, [31, 29 if y % 4 == 0 and (y % 100 != 0 or y % 400 == 0) else 28,
                          31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m - 1])
    return date(y, m, day)


def _target_date(basis, today):
    if basis == "전일":
        return today - timedelta(days=1)
    if basis == "전주":
        return today - timedelta(days=7)
    if basis == "전월":
        return _months_ago(today, 1)
    if basis == "3개월":
        return _months_ago(today, 3)
    if basis == "반년":
        return _months_ago(today, 6)
    if basis == "연초":
        return date(today.year, 1, 1)
    if basis == "작년말":
        return date(today.year - 1, 12, 31)
    return today


def target_date_of(basis, today=None):
    """비교기준 문자열 → 목표 날짜(date). 대시보드가 차트 시작일 계산에도 재사용."""
    return _target_date(basis, today or date.today())


def series(owner, since_iso=None):
    """owner(스냅샷 키)의 일별 총자산 시계열. since_iso 이상만.
    반환: [{date, total, stock, cash}, ...] 날짜 오름차순."""
    out = []
    for r in _load():
        if r["owner"] != owner:
            continue
        if since_iso and r["date"] < since_iso:
            continue
        try:
            out.append(dict(date=r["date"], total=float(r["total_asset_krw"]),
                            stock=float(r["stock_value"]), cash=float(r["cash"])))
        except (ValueError, TypeError):
            continue
    return sorted(out, key=lambda x: x["date"])


def compare_asof(owner, target_iso, current_total):
    """명시된 목표일(target_iso 'YYYY-MM-DD') 기준 스냅샷 대조.
    그 날짜 이하 가장 가까운 스냅샷을 쓰고, 정확히 일치하지 않으면 approx=True."""
    rows = [r for r in _load() if r["owner"] == owner and r["date"] <= target_iso]
    if not rows:
        return None
    best = max(rows, key=lambda r: r["date"])
    try:
        base_val = float(best["total_asset_krw"])
    except (ValueError, TypeError):
        return None
    diff = current_total - base_val
    pct = diff / base_val if base_val else 0
    return dict(base_date=best["date"], base_value=base_val,
                diff=diff, pct=pct, approx=(best["date"] != target_iso))


def compare(owner, basis, current_total, today=None):
    """비교기준(전일/전주/전월/연초/작년말) 시점의 스냅샷 조회 → 증감 요약.
    정확한 날짜 스냅샷이 없으면 그 이하 가장 가까운 날짜로 대체(approx=True)."""
    today = today or date.today()
    target = _target_date(basis, today).isoformat()
    r = compare_asof(owner, target, current_total)
    if r:
        r["basis"] = basis
    return r
