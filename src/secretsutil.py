# -*- coding: utf-8 -*-
"""
secretsutil.py — 배포처마다 다른 '비밀값' 저장 방식을 한 곳에서 흡수한다.

  · Streamlit Community Cloud / 로컬 : .streamlit/secrets.toml  → st.secrets
  · Hugging Face Spaces              : Settings > Secrets       → 환경변수

둘 다 지원해야 호스트를 갈아타도 코드를 안 고친다. 조회 순서는 st.secrets 우선,
없으면 환경변수. 환경변수 이름은 SECTION_KEY를 대문자로 (예: gdrive/folder_id → GDRIVE_FOLDER_ID).
"""
import os


def get(key, section=None, default=None):
    """비밀값 하나 조회. section을 주면 st.secrets[section][key] / 환경변수 SECTION_KEY 순으로 찾는다."""
    try:
        import streamlit as st
        if section:
            sec = st.secrets.get(section)
            if sec is not None:
                # secrets.toml의 섹션은 dict처럼 동작하지만 get이 없을 수도 있어 방어적으로 처리
                try:
                    val = sec.get(key)
                except AttributeError:
                    val = sec[key] if key in sec else None
                if val not in (None, ""):
                    return val
        else:
            val = st.secrets.get(key)
            if val not in (None, ""):
                return val
    except Exception:
        pass   # secrets 미설정/파일없음 — 환경변수로 폴백

    env_name = (f"{section}_{key}" if section else key).upper()
    val = os.environ.get(env_name)
    return val if val not in (None, "") else default
