# -*- coding: utf-8 -*-
"""
profile.py — 프로필(샘플/본인) 선택 + 세션별 데이터 폴더 분리

Streamlit Cloud처럼 여러 브라우저 세션이 같은 서버 프로세스를 공유하는 배포 환경에서도
세션마다 다른 프로필의 데이터를 안전하게 격리해서 보도록, "지금 데이터 폴더가 어디인지"를
모듈 임포트 시점(프로세스 공용)이 아니라 **매 호출 시점(세션 전용 st.session_state 참조)**에
결정한다. 다른 src 모듈들은 파일을 열 때마다 이 모듈의 data_dir()을 불러써야 한다
(모듈 상단에서 한 번만 계산해 캐싱하면 세션 간 데이터가 섞이는 사고가 난다).
"""
from pathlib import Path

import streamlit as st

BASE = Path(__file__).resolve().parent.parent   # Simul v9/
PROFILES = ["샘플", "본인"]
DEFAULT_PROFILE = "샘플"
SESSION_KEY = "_v9_profile"


_fallback_profile = None  # streamlit 세션 컨텍스트 밖(CLI 스크립트 등)에서만 쓰임


def get_profile():
    """현재 세션이 고른 프로필. 아직 선택 전이면 None (dashboard.py가 게이트로 막음).
    streamlit 세션 컨텍스트 밖(예: `python report.py` 직접 실행)에서는
    session_state 접근이 실패하므로 모듈 전역 폴백을 쓴다."""
    try:
        return st.session_state.get(SESSION_KEY)
    except Exception:
        return _fallback_profile


def set_profile(name):
    global _fallback_profile
    if name not in PROFILES:
        raise ValueError(f"unknown profile: {name}")
    try:
        st.session_state[SESSION_KEY] = name
    except Exception:
        _fallback_profile = name


def data_dir():
    """현재 세션 프로필의 data/ 폴더. 선택 전 호출되면 방어적으로 샘플로 폴백."""
    p = get_profile() or DEFAULT_PROFILE
    d = BASE / "data" / p
    d.mkdir(parents=True, exist_ok=True)
    return d


def out_dir():
    """현재 세션 프로필의 out/ 폴더 (리포트 저장용)."""
    p = get_profile() or DEFAULT_PROFILE
    d = BASE / "out" / p
    d.mkdir(parents=True, exist_ok=True)
    return d


# 앱 단위 설정(프로필 선택 '전'에 읽어야 하므로 프로필별 폴더가 아니라 data/ 바로 아래).
# 비밀번호는 평문이 아니라 해시로 저장하고, 이 파일은 .gitignore 대상이다.
APP_CONFIG = BASE / "data" / "app_config.json"


def _load_app_config():
    import json
    try:
        with open(APP_CONFIG, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _hash(pw):
    import hashlib
    return hashlib.sha256(pw.encode("utf-8")).hexdigest()


def set_owner_password(pw):
    """로컬에서 '본인' 프로필 비밀번호 설정/해제(빈 문자열이면 해제)."""
    import json
    cfg = _load_app_config()
    if pw:
        cfg["owner_password_sha256"] = _hash(pw)
    else:
        cfg.pop("owner_password_sha256", None)
    APP_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    with open(APP_CONFIG, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def owner_password_required():
    """'본인' 프로필 진입 시 비밀번호를 요구할지. 배포 환경의 secrets(OWNER_PASSWORD) 또는
    로컬에서 설정한 해시가 있으면 활성. 둘 다 없으면 조용히 비활성."""
    import secretsutil
    if secretsutil.get("owner_password"):
        return True
    return bool(_load_app_config().get("owner_password_sha256"))


def verify_owner_password(pw):
    if not pw:
        return False
    import secretsutil
    expected = secretsutil.get("owner_password")
    if expected:
        return pw == expected
    saved = _load_app_config().get("owner_password_sha256")
    return bool(saved) and _hash(pw) == saved
