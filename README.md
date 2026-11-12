---
title: 자산관리 v9
emoji: 🗂️
colorFrom: blue
colorTo: green
sdk: streamlit
app_file: dashboard.py
pinned: false
---

# v9 — 거래원장(Ledger) 기반 통합 자산관리

v6까지는 **자산현황 엑셀을 캡처**해서 보는 방식이었습니다.
v7부터는 **거래원장(transactions.csv) 하나만 손으로 입력**하고, 프로그램이
그것을 누적 재생(replay)해서 현황·손익·세금·현금흐름·리포트를 **전부 계산**합니다.

## v9에서 추가된 것
- **탭별 모듈 분할**: `dashboard.py`는 얇은 오케스트레이터, 실제 로직은 `tabs/*.py` + `src/appctx.py`(전역 컨텍스트)로 분리.
- **전역 필터(사이드바)**: 소유자·기간(비교기준 pills: 전일/전주/전월/3개월/반년/연초/작년말/직접입력)·자산군·종목(전체선택 체크박스) — 모든 탭 공통 적용.
- **📊 현황 / 📒 매매일지**: 신한 HTS [1721] 스타일 기간수익률(시작·평가 순자산/입출금/손익/수익률 + 일별테이블 + 전환형 그래프). 매매일지는 매매+소득기록(배당/이자/쿠폰)에 일련번호를 부여하고 그래프에 번호 마커로 연결.
- **🧾 세금리포트**: 소유자 필터만 반영(기간 필터 무시, 해당 과세연도 기준).
- **🎯 IPS준수**: 계획vs실적 그래프 삭제 → 목표 미달/임계 초과 시 🗒️ 액션아이템에 자동 등록.
- **🚦 액션추천**: 종목별 전략 기본값 저장(`settings.json` strategy_defaults), 매수/매도 액션 원클릭 등록, 실제매매+전략시그널 오버레이 차트.
- **🧪 시뮬레이션**: 트렌드 탭을 통합, v6 마삼룰 비교 시뮬레이터(2패널) 내장, 환율차트 국가선택(USD/BRL/JPY/EUR/CNY).
- **💵 현금흐름**: 예상(스케줄) vs 실제수령 병기, 월 막대 클릭 시 구성 항목 표시.
- **🌐 네트워크 접속**: 실행 시 다른 기기(같은 와이파이) 접속 여부 선택 가능 (`launcher.py` 참고).

## v8에서 추가된 것 (v9에서도 유지)
- **🗒️ 액션아이템 트래커**: 배당 입금·이월과세 D-30·금융소득 80%·증여세 D-14·연납입 미달 시
  자동 생성. 체크박스로 완료 처리. Notion 연동(설정 탭에서 토큰 등록) 시 휴대폰에서도 체크 가능.
- **🎯 IPS 준수현황**: 설정 탭에서 자신의 IPS 목표(자산군 원금/계좌 연납입/종목 비중/금융소득 풀)를
  자유롭게 등록하면 진행률 바로 표시. 연초 계획 vs 실적 월별 그래프.
- **🧾 세금리포트 개선**: 금융소득 3분류(비과세/분리과세/종합과세) × (YTD/연말예상) +
  비교과세(기납부 14% 크레딧) 기반 예상 추가납부세액. 기타 종합소득은 설정 탭에서 연도별 입력.
- **📊 기간비교**: 현황 탭 상단에서 전일/전주/전월/연초/작년말 대비 증감. 매일 앱을 열면
  총자산 스냅샷(asset_snapshots.csv)이 자동으로 쌓임.
- **⚙️ 설정 탭**: 종합소득·IPS 목표·임계값·Notion — 코드 수정 없이 숫자만 바꾸면 됨.

> 설계 원칙 (SPEC v1.0)
> 1. `data/transactions.csv`(거래원장)가 **유일한 손입력**. 나머지는 계산 결과물.
> 2. 평가금액·수익률·평단·세금·현금잔고는 **절대 손으로 입력하지 않는다**.
> 3. `BUY`를 기록하면 현금이 **자동 차감**된다 → 총자산이 부풀려지는 사고가 구조적으로 불가능.
> 4. 세법은 코드에 박아넣는다(`src/tax_rules.py`).

---

## 폴더 구조
```
Simul v9/
├─ dashboard.py            ← 실행 진입점 (streamlit) — 얇은 오케스트레이터
├─ migrate_seed.py         ← 기존 명세서 xlsx → 최초 SEED 원장 생성 (1회용)
├─ tabs/                   ← 탭별 모듈 (v9) — 각 파일이 render(ctx) 하나를 노출
│  ├─ shared.py            ← 신한 [1721] 스타일 기간수익률 공용 위젯
│  ├─ tab_status.py / tab_journal.py / tab_tax.py / tab_ips.py / tab_action.py
│  ├─ tab_sim.py (트렌드+시뮬+마삼룰비교+환율) / tab_cash.py / tab_items.py
│  └─ tab_input.py / tab_upload.py / tab_report.py / tab_settings.py
├─ data/
│  ├─ transactions.csv     ← ★ 거래원장 (유일한 손입력, 여기만 편집)
│  ├─ assets.csv           ← 자산 마스터 (티커·자산군·시세소스)
│  ├─ accounts.csv         ← 계좌 마스터 (RIA 등 제약)
│  ├─ action_items.csv     ← 액션아이템 (자동생성+수동, 대시보드에서 체크)
│  ├─ other_income.csv     ← 연도별 기타 종합소득 (설정 탭에서 입력)
│  ├─ asset_snapshots.csv / asset_snapshots_detail.csv  ← 일별 스냅샷 (자동, 기간비교·수익률화면용)
│  ├─ settings.json        ← 임계값·IPS 목표·종목별 전략 기본값 (설정/액션추천 탭에서 편집)
│  └─ notion_config.json   ← Notion 토큰 (설정 탭에서 입력, 로컬 전용)
├─ src/
│  ├─ appctx.py            ← 전역 컨텍스트: 사이드바 필터 + 탭 공유 계산 (v9)
│  ├─ ledger.py            ← 원장 재생: 포지션·현금·평단·실현손익
│  ├─ prices.py            ← 시세·환율 (yfinance)
│  ├─ tax_rules.py         ← 이월과세·RIA·양도세·금융소득종합과세
│  ├─ marsam.py            ← 마삼룰 상태머신 (HOLD/WAIT_B/WAIT_E)
│  ├─ cashflow.py          ← 배당·쿠폰 현금흐름
│  ├─ report.py            ← 1페이지 md 리포트
│  ├─ asset_meta.py        ← 종목명↔티커·자산군 매핑
│  ├─ action_items.py      ← 액션아이템 트래커 + 자동생성 트리거(IPS미달 포함, v9)
│  ├─ ips.py               ← IPS 목표 진행률
│  ├─ snapshots.py         ← 총자산 스냅샷 · 기간비교 (3개월/반년 추가, v9)
│  ├─ notion_sync.py       ← Notion 동기화
│  └─ settings.py          ← 전역 설정 로드/저장
└─ out/                    ← report_YYYYMMDD.md (자동 생성)
```

## 매일 사용법
1. `실행.bat`(윈도우) 또는 `실행_맥용.command`(맥) → **1번 [v9] 원장버전** 선택.
2. **거래가 생기면** → `➕ 거래입력` 탭에서 1줄 기록 (thesis 꼭 남기기). 2분.
   - 매수/매도 시 현금은 자동 차감·증가됩니다. 평가액·손익은 자동 계산.
3. 나머지 탭(현황·매매일지·세금·트렌드·시뮬·현금흐름)은 **볼 뿐** 입력하지 않습니다.
4. 상담이 필요하면 `📋 리포트` 탭의 md만 복사해 붙여넣기 (토큰 절약).

**매일 가격을 보지 마세요.** 마삼룰 −3% 트리거만 코드가 감시합니다.
신호와 노이즈를 분리하는 것이 이 시스템의 목적입니다.

---

## 거래원장(transactions.csv) 작성 규칙

| 컬럼 | 필수 | 설명 |
|---|:--:|---|
| `txn_id` | ✓ | `YYYYMMDD-NNN` (대시보드가 자동 부여) |
| `date` | ✓ | 거래일(체결일) YYYY-MM-DD |
| `settle_date` |  | 결제일(해외 T+3). 양도세 귀속연도 기준. 공란=date |
| `owner` | ✓ | 본인 / 배우자 / 장남 / 차남 / 부친 / 모친 |
| `account` | ✓ | 계좌 (accounts.csv 참조) |
| `asset_id` | ✓ | 티커/코드. 현금은 `CASH.USD`/`CASH.KRW` |
| `asset_class` | ✓ | US_STOCK/KR_STOCK/KR_ETF/BOND_KR/BOND_FX/FUND/ELS/CASH/CRYPTO/REALESTATE/PENSION/OTHER |
| `type` | ✓ | 아래 표 |
| `qty` | ✓ | 수량(양수). **부호는 type이 결정** |
| `price` |  | 단가(거래통화) |
| `ccy` | ✓ | KRW / USD / BRL |
| `fx` |  | 거래시점 환율(원/외화). KRW=1 |
| `amount` |  | 총액. 공란이면 qty×price |
| `fee` / `tax` |  | 수수료 / 원천징수 |
| `cash_account` |  | 현금 출입 계좌. 공란=account |
| `link_id` |  | 연결거래(증여 OUT↔IN, 환전) |
| `tag` |  | MARSAM / RIA / ENERGY / SEED 등 (`;`로 복수) |
| `note` |  | **thesis — 왜 샀는지 반드시 기록** |

### type (거래유형)
| type | 자산 | 현금 | 비고 |
|---|:--:|:--:|---|
| BUY | +qty | −amount | 매수 (현금 자동차감) |
| SELL | −qty | +amount | 매도 (양도세·실현손익 계산) |
| DEPOSIT / WITHDRAW | — | +/− | 입·출금 (WITHDRAW는 RIA 감시) |
| DIVIDEND / INTEREST | — | +amount | 배당·이자 (금융소득 집계) |
| GIFT_IN / GIFT_OUT | +/−qty | — | 증여 (이월과세 시계 시작) |
| TRANSFER_IN / OUT | +/−qty | — | 대체입·출고 (link_id) |
| FEE / TAX | — | −amount | 수수료·세금 |
| FX | — | ± | 환전 (2줄, link_id 연결) |
| SPLIT | ×ratio | — | 액면분할 (qty=배수) |
| REVALUE | — | — | 시세없는 자산 평가 갱신 (price=새 평가액) |

> SEED(기초잔고) 거래는 `tag=SEED`가 붙어 있으며, 현금을 차감하지 않습니다
> (개시 잔고이므로). 처음 마이그레이션으로 자동 생성된 것이며 편집하지 마세요.

---

## 다시 마이그레이션(초기화)이 필요할 때
`data/transactions.csv`가 곧 원장입니다. 새로 시작하려면:
```
python migrate_seed.py "경로/명세서.xlsx"
```
⚠️ 이미 원장에 실제 거래를 쌓았다면 덮어쓰지 마세요(그동안 기록이 사라집니다).

---

## 세법 가정값 (src/tax_rules.py — 코드에 고정)
- 해외주식 양도세: (실현손익 − 250만 기본공제) × 22%
- 금융소득종합과세: 연 배당+이자(비과세 제외) 2,000만원 초과 시 대상
- 이월과세: 증여 후 1년 내 매도 시 취득가 = 증여자 평단 (경고 표시)
- RIA 인출금지: 매도 후 1년 내 인출 시 전액 추징 (감시)

실제 신고는 세무 전문가 확인이 필요합니다. 본 도구는 개인 참고용입니다.
