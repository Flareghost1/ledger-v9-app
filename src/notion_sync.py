# -*- coding: utf-8 -*-
"""
notion_sync.py — 액션아이템 ↔ Notion 데이터베이스 동기화 (v8 명세 §1-4)
data/notion_config.json 에 token/database_id를 넣으면 동작. 미설정이면 조용히 skip.

Notion DB 속성 매핑 (설정 탭 안내대로 DB를 만들면 됨):
  제목(title)  ← title
  카테고리(select) ← category
  기한(date)   ← due_date
  완료(checkbox) ← status == DONE

동기화 방향:
  push_open_items : 로컬 OPEN 항목 중 notion_page_id 없는 것 → Notion에 생성
  pull_status     : Notion 완료 체크박스 → 로컬 status=DONE 반영 (휴대폰에서 체크한 것)
"""
import json
from datetime import date

import profile as PROFILE


def _config_path():
    return PROFILE.data_dir() / "notion_config.json"


def load_config():
    try:
        with open(_config_path(), encoding="utf-8") as f:
            cfg = json.load(f)
        return cfg if cfg.get("token") and cfg.get("database_id") else None
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def save_config(token, database_id):
    path = _config_path()
    path.parent.mkdir(exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"token": token, "database_id": database_id}, f, ensure_ascii=False, indent=2)


def get_client():
    """notion_client.Client 또는 None(미설정). 패키지 미설치면 ImportError 메시지 반환."""
    cfg = load_config()
    if not cfg:
        return None, "Notion 미설정 — 설정 탭에서 토큰과 데이터베이스 ID를 입력하세요."
    try:
        from notion_client import Client
    except ImportError:
        return None, "notion-client 패키지가 없습니다. 실행.bat의 설치 메뉴를 다시 실행하세요."
    return Client(auth=cfg["token"]), None


def test_connection():
    """연결 테스트: DB 메타 조회. 반환 (성공여부, 메시지)."""
    client, err = get_client()
    if err:
        return False, err
    cfg = load_config()
    try:
        db = client.databases.retrieve(cfg["database_id"])
        title = "".join(t.get("plain_text", "") for t in db.get("title", []))
        return True, f"연결 성공: '{title or '(제목 없음)'}' 데이터베이스"
    except Exception as e:
        return False, f"연결 실패: {e}"


def _item_props(item):
    props = {
        "제목": {"title": [{"text": {"content": item.get("title", "")[:200]}}]},
        "카테고리": {"select": {"name": item.get("category") or "기타"}},
        "완료": {"checkbox": item.get("status") == "DONE"},
    }
    if item.get("due_date"):
        props["기한"] = {"date": {"start": item["due_date"]}}
    return props


def push_open_items(items):
    """notion_page_id 없는 항목을 Notion에 생성, page_id를 items에 기록.
    반환 (생성수, 에러메시지 or None). 호출부에서 save_items 필요."""
    client, err = get_client()
    if err:
        return 0, err
    cfg = load_config()
    pushed = 0
    try:
        for it in items:
            if it.get("notion_page_id") or it.get("status") == "DISMISSED":
                continue
            page = client.pages.create(parent={"database_id": cfg["database_id"]},
                                       properties=_item_props(it))
            it["notion_page_id"] = page["id"]
            pushed += 1
    except Exception as e:
        return pushed, f"Notion 생성 실패: {e}"
    return pushed, None


def pull_status(items):
    """Notion 완료 체크박스 → 로컬 반영. 반환 (변경수, 에러메시지 or None)."""
    client, err = get_client()
    if err:
        return 0, err
    changed = 0
    try:
        for it in items:
            pid = it.get("notion_page_id")
            if not pid or it.get("status") != "OPEN":
                continue
            page = client.pages.retrieve(pid)
            done = page.get("properties", {}).get("완료", {}).get("checkbox", False)
            if done:
                it["status"] = "DONE"
                it["completed_date"] = date.today().isoformat()
                changed += 1
    except Exception as e:
        return changed, f"Notion 조회 실패: {e}"
    return changed, None


def push_status_updates(items):
    """로컬에서 DONE 처리된 항목의 Notion 체크박스도 갱신. 반환 (변경수, 에러 or None)."""
    client, err = get_client()
    if err:
        return 0, err
    changed = 0
    try:
        for it in items:
            pid = it.get("notion_page_id")
            if not pid or it.get("status") != "DONE":
                continue
            page = client.pages.retrieve(pid)
            if not page.get("properties", {}).get("완료", {}).get("checkbox", False):
                client.pages.update(pid, properties={"완료": {"checkbox": True}})
                changed += 1
    except Exception as e:
        return changed, f"Notion 갱신 실패: {e}"
    return changed, None
