# -*- coding: utf-8 -*-
"""
settings.py — 전역 설정 (data/settings.json)
임계값·IPS 목표를 코드가 아니라 설정 파일에 둔다(v8 명세 §5-2).
IPS 목표는 개인마다 다르므로 하드코딩하지 않고, 설정 탭에서 자유롭게
추가/수정/삭제할 수 있는 범용 목표 리스트(ips_goals)로 관리한다.

ips_goals 항목 스키마:
  id             고유 식별자 (자동 부여)
  label          화면에 표시할 이름 (예: "브라질국채 원금 5억")
  metric         측정 방식 (아래 METRICS 중 하나)
  match          측정 대상 (asset_class 코드 / 계좌명 / asset_id, metric에 따라)
  target         목표값 (원 또는 %) — None이면 "목표 미정, 현재값만 표시"
  target_by_year 연도별 목표 dict (account_deposit_annual 전용, {"2026": 40000000})
"""
import json

import profile as PROFILE


def _settings_path():
    return PROFILE.data_dir() / "settings.json"

# metric 코드 → (한글명, match에 넣을 것, target 단위)
METRICS = {
    "asset_class_sum":        ("자산군 원금 합계", "자산군 코드 (예: BOND_FX)", "원"),
    "account_deposit_annual": ("계좌 연간 입금 누적", "계좌명 (예: ISA계좌)", "원(연도별)"),
    "position_weight_pct":    ("종목 비중(%)", "종목 asset_id (예: AAPL)", "%"),
    "financial_income_ratio": ("금융소득 종합과세 풀", "(자동 — 원장 금융소득)", "원"),
}

DEFAULTS = {
    "fin_income_threshold": 20_000_000,   # 금융소득종합과세 기준(세법)
    "ips_goals": [],                       # 사용자가 설정 탭에서 추가
}


def load_settings():
    """settings.json 로드. 없거나 키가 빠져 있으면 기본값으로 병합(스키마 진화 안전)."""
    merged = dict(DEFAULTS)
    try:
        with open(_settings_path(), encoding="utf-8") as f:
            saved = json.load(f)
        for k, v in saved.items():
            merged[k] = v
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    return merged


def save_settings(settings):
    path = _settings_path()
    path.parent.mkdir(exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(settings, f, ensure_ascii=False, indent=2)


def next_goal_id(settings):
    ids = [g.get("id", 0) for g in settings.get("ips_goals", [])]
    return (max(ids) + 1) if ids else 1
