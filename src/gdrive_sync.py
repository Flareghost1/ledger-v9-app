# -*- coding: utf-8 -*-
"""
gdrive_sync.py — data/ 폴더 ↔ Google Drive 동기화 (v9 §12: 클라우드 배포 데이터 영속성)

Streamlit Community Cloud처럼 로컬 디스크가 재배포 시 초기화되는(ephemeral) 환경에서,
Google Drive의 지정 폴더를 "진짜 원본"으로 삼아 앱 시작 시 내려받고(pull), 저장할 때마다
다시 올린다(push). notion_sync.py와 동일한 철학: 미설정이면 조용히 skip, 절대 대시보드를
막지 않는다. 인증정보는 코드/데이터 파일이 아니라 Streamlit secrets에만 둔다(git에 안 감).

필요한 secrets (.streamlit/secrets.toml, 로컬은 파일로 · 배포는 Streamlit Cloud 설정에서):
  [gdrive]
  service_account_json = '''{ ... 서비스계정 키 JSON 전체 ... }'''
  folder_id = "본인 데이터를 넣을 Drive 폴더 ID"

동기화 대상은 "본인" 프로필뿐이다(샘플은 코드에 포함된 고정 데모라 동기화 불필요).
"""
import io
import json

import profile as PROFILE

SYNCED_PROFILE = "본인"
# data/ 바로 아래 파일만 동기화 대상 (backups/ 등 하위 폴더는 제외 — 용량·복잡도 방지)
SYNC_FILES = ["transactions.csv", "assets.csv", "accounts.csv", "action_items.csv",
              "other_income.csv", "settings.json", "asset_snapshots.csv",
              "asset_snapshots_detail.csv", "notion_config.json"]


def _secret(key):
    """secrets.toml의 [gdrive] 섹션 또는 환경변수 GDRIVE_* (Hugging Face Spaces 등)."""
    import secretsutil
    return secretsutil.get(key, section="gdrive")


def is_configured():
    return bool(_secret("service_account_json") and _secret("folder_id"))


def _cfg():
    return _secret("service_account_json"), _secret("folder_id")


def _get_service():
    """googleapiclient Drive v3 service, 또는 (None, 에러메시지)."""
    if not is_configured():
        return None, "Google Drive 미설정 — secrets.toml에 [gdrive] 섹션이 필요합니다."
    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
    except ImportError:
        return None, "google-api-python-client 패키지가 없습니다 (requirements.txt 설치 필요)."
    try:
        sa_json, _folder_id = _cfg()
        info = json.loads(sa_json)
        creds = service_account.Credentials.from_service_account_info(
            info, scopes=["https://www.googleapis.com/auth/drive"])
        return build("drive", "v3", credentials=creds, cache_discovery=False), None
    except Exception as e:
        return None, f"Drive 인증 실패: {e}"


def _list_remote_files(service, folder_id):
    """{파일명: file_id} — 대상 폴더 바로 아래 파일만."""
    out = {}
    page_token = None
    q = f"'{folder_id}' in parents and trashed = false"
    while True:
        resp = service.files().list(q=q, spaces="drive", fields="nextPageToken, files(id, name)",
                                    pageToken=page_token).execute()
        for f in resp.get("files", []):
            out[f["name"]] = f["id"]
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return out


def pull_all(profile=None):
    """Drive 폴더의 파일들을 로컬 data/본인/ 로 내려받아 덮어쓴다(Drive가 원본).
    반환 (내려받은 파일수, 에러메시지 or None). 대상 프로필이 '본인'이 아니면 조용히 skip."""
    profile = profile or PROFILE.get_profile()
    if profile != SYNCED_PROFILE:
        return 0, None
    service, err = _get_service()
    if err:
        return 0, err
    try:
        from googleapiclient.http import MediaIoBaseDownload
        _sa, folder_id = _cfg()
        remote = _list_remote_files(service, folder_id)
        data_dir = PROFILE.BASE / "data" / profile
        data_dir.mkdir(parents=True, exist_ok=True)
        n = 0
        for name in SYNC_FILES:
            if name not in remote:
                continue
            request = service.files().get_media(fileId=remote[name])
            buf = io.BytesIO()
            downloader = MediaIoBaseDownload(buf, request)
            done = False
            while not done:
                _status, done = downloader.next_chunk()
            (data_dir / name).write_bytes(buf.getvalue())
            n += 1
        return n, None
    except Exception as e:
        return 0, f"Drive 다운로드 실패: {e}"


def push_all(profile=None):
    """로컬 data/본인/ 파일들을 Drive 폴더로 올린다(같은 이름 있으면 갱신, 없으면 생성).
    반환 (올린 파일수, 에러메시지 or None)."""
    profile = profile or PROFILE.get_profile()
    if profile != SYNCED_PROFILE:
        return 0, "샘플 프로필은 동기화 대상이 아닙니다."
    service, err = _get_service()
    if err:
        return 0, err
    try:
        from googleapiclient.http import MediaIoBaseUpload
        _sa, folder_id = _cfg()
        remote = _list_remote_files(service, folder_id)
        data_dir = PROFILE.BASE / "data" / profile
        n = 0
        for name in SYNC_FILES:
            path = data_dir / name
            if not path.exists():
                continue
            media = MediaIoBaseUpload(io.BytesIO(path.read_bytes()), mimetype="text/plain", resumable=False)
            if name in remote:
                service.files().update(fileId=remote[name], media_body=media).execute()
            else:
                service.files().create(body={"name": name, "parents": [folder_id]}, media_body=media).execute()
            n += 1
        return n, None
    except Exception as e:
        return 0, f"Drive 업로드 실패: {e}"


def push_file(name, profile=None):
    """파일 하나만 Drive에 올린다(저장 직후 자동 동기화용 — push_all보다 가볍다).
    반환 (성공여부, 에러메시지 or None)."""
    profile = profile or PROFILE.get_profile()
    if profile != SYNCED_PROFILE:
        return False, None
    service, err = _get_service()
    if err:
        return False, err
    path = PROFILE.BASE / "data" / profile / name
    if not path.exists():
        return False, f"{name} 파일이 없습니다."
    try:
        from googleapiclient.http import MediaIoBaseUpload
        _sa, folder_id = _cfg()
        q = f"'{folder_id}' in parents and trashed = false and name = '{name}'"
        resp = service.files().list(q=q, spaces="drive", fields="files(id)").execute()
        existing = resp.get("files", [])
        media = MediaIoBaseUpload(io.BytesIO(path.read_bytes()), mimetype="text/plain", resumable=False)
        if existing:
            service.files().update(fileId=existing[0]["id"], media_body=media).execute()
        else:
            service.files().create(body={"name": name, "parents": [folder_id]}, media_body=media).execute()
        return True, None
    except Exception as e:
        return False, f"Drive 업로드 실패({name}): {e}"


def autopush_toast(*names, profile=None):
    """autopush() + 실패 시에만 조용한 토스트 알림(성공은 UI를 방해하지 않게 알리지 않음)."""
    import streamlit as st
    _ok, failed = autopush(*names, profile=profile)
    if failed:
        st.toast(f"☁️ Drive 자동동기화 일부 실패 — 설정 탭에서 수동으로 다시 올려주세요.", icon="⚠️")


def autopush(*names, profile=None):
    """저장 직후 호출용 — 미설정이거나 '본인'이 아니면 조용히 아무것도 안 한다.
    실패해도 예외를 던지지 않는다(대시보드 흐름을 절대 막지 않기 위함) — 대신
    (성공수, 실패목록)을 반환하니 호출부에서 필요하면 조용히 경고만 띄운다."""
    profile = profile or PROFILE.get_profile()
    if profile != SYNCED_PROFILE or not is_configured():
        return 0, []
    ok, failed = 0, []
    for name in names:
        try:
            success, err = push_file(name, profile)
            if success:
                ok += 1
            elif err:
                failed.append(f"{name}: {err}")
        except Exception as e:
            failed.append(f"{name}: {e}")
    return ok, failed


def test_connection():
    """폴더 접근 확인. 반환 (성공여부, 메시지)."""
    service, err = _get_service()
    if err:
        return False, err
    try:
        _sa, folder_id = _cfg()
        meta = service.files().get(fileId=folder_id, fields="id, name").execute()
        return True, f"연결 성공: '{meta.get('name')}' 폴더"
    except Exception as e:
        return False, f"연결 실패: {e}"
