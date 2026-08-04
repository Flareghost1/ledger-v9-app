# v9 배포 가이드 — Streamlit Community Cloud + Google Drive

여행 중에도 폰·노트북에서 집 PC와 같은 데이터로 v9를 쓰기 위한 배포 방법입니다.

**호스트 선정 경위**: Hugging Face Spaces는 2026-08 기준 무료 플랜에서 Static만 남고
Streamlit SDK가 사라져 쓸 수 없습니다. Streamlit Community Cloud는 무료지만 GitHub 앱이
"공개 저장소" 권한만 요청해 비공개 저장소를 배포할 수 없습니다. 그래서 **코드만 담은 공개
저장소**를 따로 만들어 배포합니다.

## 저장소 구성 (중요)

| 저장소 | 공개여부 | 용도 |
|---|---|---|
| `Flareghost1/investment-ledger` | **비공개** | 기존 백업. v6/v7/v8과 **실제 원장 데이터가 들어있어 절대 공개 금지** |
| `Flareghost1/ledger-v9-app` | 공개 | 배포용. 코드 + 가상 샘플데이터만, 히스토리 1커밋 |

로컬 `Simul v9`에는 두 원격이 모두 연결돼 있습니다.

**① 비공개 백업 (평소 커밋)**

```bash
git push
```

**② 공개 저장소에 반영 — 반드시 아래 한 줄로**

```bash
git checkout --orphan public-tmp && git add -A && git commit -m "자산관리 v9 배포" && git push public public-tmp:main --force && git checkout v9 && git branch -D public-tmp
```

⚠️ **`git push public v9:main --force` 를 그냥 쓰면 안 됩니다.** v9 브랜치의 과거 커밋이
통째로 공개되는데, 초기 커밋에는 나중에 코드에서 뺀 실명이 그대로 남아 있습니다.
위 명령은 부모 없는 새 커밋 하나만 올리므로 과거 기록이 따라가지 않습니다
(실제로 이 실수를 한 번 냈다가 되돌린 적이 있습니다).

올린 뒤 아래로 한 번 더 확인하세요 — 아무것도 안 나와야 정상입니다:

```bash
cd /tmp && rm -rf chk && git clone -q https://github.com/Flareghost1/ledger-v9-app.git chk && cd chk && git log --all -p | grep -nE "김|[0-9]{10}-[0-9]{2}" | head
```

- 코드: 공개 저장소 `ledger-v9-app`
- 데이터: Google Drive 폴더 (앱이 시작할 때 내려받고, ⚙️설정 탭에서 수동으로 올림)
- 접근 제한: 앱 안에서 "본인" 진입 시 비밀번호(`OWNER_PASSWORD`)

---

## 1. Google Cloud에서 서비스 계정 만들기 (Drive 접근용)

1. https://console.cloud.google.com 접속 → 새 프로젝트 생성 (이름 아무거나, 예: `v9-ledger`)
2. 좌측 메뉴 **API 및 서비스 → 라이브러리** → "Google Drive API" 검색 → **사용(Enable)**
3. **API 및 서비스 → 사용자 인증 정보 → 사용자 인증 정보 만들기 → 서비스 계정**
   - 이름 아무거나 (예: `v9-drive-sync`) → 만들기 → 완료(역할 부여는 건너뛰어도 됨)
4. 방금 만든 서비스 계정 클릭 → **키(Keys)** 탭 → **키 추가 → 새 키 만들기 → JSON** → 다운로드
   - 브라우저 확인창 없이 **다운로드 폴더에 바로 저장**됩니다. 창이 닫혔어도 다운로드 폴더를 먼저 확인하세요.
   - 못 찾으면: 같은 화면에서 그 키를 삭제하고 **키를 새로 만들면** 됩니다(같은 키는 재다운로드 불가).
   - JSON 안의 `"client_email": "...@....iam.gserviceaccount.com"` 를 다음 단계에서 씁니다.

## 2. Google Drive에 폴더 만들고 서비스 계정과 공유

1. drive.google.com 에서 새 폴더 생성 (예: `v9-원장데이터`)
2. 로컬 `data/본인/` 안의 파일들을 이 폴더에 업로드
   (transactions.csv, assets.csv, accounts.csv, action_items.csv, settings.json,
    other_income.csv, asset_snapshots.csv, asset_snapshots_detail.csv)
3. 폴더 우클릭 → **공유** → 1번의 서비스 계정 이메일(`...iam.gserviceaccount.com`)을 **편집자**로 추가
   - ⚠️ 이 단계를 빼먹으면 서비스 계정이 폴더를 못 봅니다(가장 흔한 실수).
4. 폴더 주소창의 마지막 부분이 **폴더 ID**: `https://drive.google.com/drive/folders/`**`이 부분`**

## 3. Streamlit Community Cloud에 배포

공개 저장소 `ledger-v9-app`은 이미 만들어져 있습니다(코드만, 히스토리 1커밋).

1. https://share.streamlit.io 접속 → **GitHub 계정(Flareghost1)으로 로그인**
2. **Create app** → **Deploy a public app from GitHub**
3. 입력:
   - **Repository**: `Flareghost1/ledger-v9-app`
   - **Branch**: `main`
   - **Main file path**: `dashboard.py`
4. **Advanced settings** → **Python version**은 3.12 권장 (3.14는 일부 패키지 미지원 가능)
5. 같은 화면의 **Secrets** 칸에 아래를 붙여넣기
   (⚠️ ```toml 같은 코드블록 표시는 넣지 말고 내용만):

```
owner_password = "원하는_비밀번호"

[gdrive]
service_account_json = '''
{ ...1번에서 받은 JSON 파일 내용 전체... }
'''
folder_id = "2번에서 확인한 폴더 ID"
```

6. **Deploy** 클릭 → 몇 분 후 고정 URL 발급 (예: `https://ledger-v9-app.streamlit.app`)

## 4. 확인

1. 발급된 URL 접속 → "🔐 본인 데이터" 선택 → 비밀번호 입력
2. 자동으로 Drive에서 데이터를 내려받습니다. 문제가 있으면 ⚙️설정 탭 맨 아래
   **☁️ Google Drive 동기화**에서 "🔌 연결 테스트"로 원인을 확인하세요.
3. 앱 URL 자체는 누구나 열 수 있지만, "본인 데이터"는 비밀번호로 막혀 있고
   실제 데이터는 Drive에만 있습니다(샘플 프로필만 비밀번호 없이 열람 가능).

## 5. 평소 사용 흐름

- 거래 입력·액션아이템 체크 등 **모든 저장은 그 서버의 로컬 파일에만** 반영됩니다.
- 작업이 끝나면 ⚙️설정 탭 → **⬆ Drive로 올리기**를 눌러야 다음 접속(다른 기기 포함)에 반영됩니다.
- ⚠️ 집 PC 로컬 실행(`실행.bat`)과 클라우드를 **동시에 쓰지 마세요** — 저장 시점이 겹치면
  나중에 올린 쪽이 상대를 덮어씁니다. 클라우드 URL 하나를 "진짜"로 정해서 쓰는 걸 권장합니다.

---

## 참고: 코드에 이미 반영된 것

- `.gitignore`가 `data/본인/`(실제 데이터)과 `.streamlit/secrets.toml`을 제외합니다.
  올라가는 건 코드와 `data/샘플/`(가짜 데모 데이터)뿐입니다.
- `src/secretsutil.py`가 secrets.toml(로컬·Streamlit Cloud)과 환경변수(Render·Docker 등)를
  **둘 다** 지원해서, 나중에 다른 호스트로 옮겨도 코드를 고칠 필요가 없습니다.
- v6 마삼룰 엔진(`engine.py`/`analysis.py`)은 `src/` 안에 사본으로 들여왔습니다 —
  예전처럼 옆 폴더(`Simul v6`)를 참조하면 클라우드엔 그 폴더가 없어 앱이 죽습니다.
  **v6 엔진을 수정하면 `src/engine.py`·`src/analysis.py`에도 반영해야 합니다.**
- 비밀번호는 `OWNER_PASSWORD`가 설정된 경우에만 요구됩니다 — 로컬에서는 지금처럼 그냥 쓰시면 됩니다.
