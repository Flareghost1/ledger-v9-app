# -*- coding: utf-8 -*-
"""
validate.py — 거래원장 CSV 엄격 검증 (업로드 전 게이트)
errors(빨강)는 저장을 막고, warnings(노랑)는 표시만 한다.
검사: 필수컬럼·enum(asset_class/type)·수량양수·txn_id형식·ccy·중복ID·숫자형·드라이런 재생(음수현금).

스키마는 시간이 지나며 진화한다(amount→amount_ccy, cash_account 폐지, fx_type 추가 등).
그래서 컬럼은 '필수'와 '알려진 선택' 두 그룹으로 나눠서, 구버전/신버전 원장을 모두 통과시킨다.
"""
import csv, re, io, tempfile, shutil
from pathlib import Path

from enums import norm_class, norm_type, ASSET_CLASS_KO, TYPE_KO

REQUIRED_COLS = ["txn_id", "date", "owner", "account", "asset_id", "asset_class", "type", "qty", "ccy"]
KNOWN_OPTIONAL_COLS = ["settle_date", "price", "fx", "fx_type", "amount", "amount_ccy",
                       "fee", "tax", "cash_account", "link_id", "tag", "note"]
KNOWN_COLS = REQUIRED_COLS + KNOWN_OPTIONAL_COLS
FX_TYPE_KNOWN = {"실제", "증여일", "이동일", "추정", "미상", "기준일", "환전실행", "결제일", ""}
# 기본 역할명. 실제 이름(형제·친척 등)은 코드가 아니라 프로필별 settings.json의
# "extra_owners"에 둔다 — 저장소가 공개돼도 개인 식별정보가 남지 않게 하기 위함.
OWNERS_BASE = {"본인", "배우자", "장남", "차남", "부친", "모친"}


def _owners_known():
    try:
        import settings as SET
        extra = SET.load_settings().get("extra_owners") or []
    except Exception:
        extra = []
    return OWNERS_BASE | set(extra)
CCY_OK = {"KRW", "USD", "BRL"}
TXN_RE = re.compile(r"^\d{8}-\d{3}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

def _is_todo(x): return isinstance(x,str) and x.strip().upper()=="TODO"
def _num_ok(x):
    if x is None or x=="" or _is_todo(x): return True
    try: float(x); return True
    except: return False

def parse_csv_text(text):
    return list(csv.DictReader(io.StringIO(text)))

def validate_rows(rows, header=None):
    errors, warnings = [], []
    owners_known = _owners_known()
    if header is not None:
        missing = [c for c in REQUIRED_COLS if c not in header]
        # amount/amount_ccy 중 최소 하나는 있어야 함(둘 다 없으면 qty*price로만 버텨야 하는데, 그건 위험하므로 권고)
        if "amount" not in header and "amount_ccy" not in header:
            warnings.append("amount/amount_ccy 컬럼이 모두 없음 — 모든 금액을 qty×price로만 추정합니다.")
        extra = [c for c in header if c not in KNOWN_COLS]
        if missing: errors.append(f"필수 컬럼 누락: {', '.join(missing)}")
        if extra: warnings.append(f"알 수 없는 컬럼(무시됨): {', '.join(extra)}")
    seen_ids = {}
    n_todo = 0
    n_lowconf = 0
    for i, r in enumerate(rows, start=2):  # 헤더가 1행
        rid = r.get("txn_id","")
        def err(m): errors.append(f"[{i}행 {rid}] {m}")
        def warn(m): warnings.append(f"[{i}행 {rid}] {m}")
        # txn_id
        if not rid: err("txn_id 없음")
        elif not TXN_RE.match(rid): err(f"txn_id 형식 오류(YYYYMMDD-NNN 아님): {rid}")
        elif rid in seen_ids: err(f"txn_id 중복(먼저 {seen_ids[rid]}행)")
        else: seen_ids[rid] = i
        # date
        if not DATE_RE.match(r.get("date","")): err(f"date 형식 오류: {r.get('date')}")
        if r.get("settle_date") and not DATE_RE.match(r["settle_date"]): warn(f"settle_date 형식 오류: {r['settle_date']}")
        # owner/account/asset_id
        if not r.get("owner"): err("owner 없음")
        elif r["owner"] not in owners_known: warn(f"미등록 owner: {r['owner']}")
        if not r.get("account"): err("account 없음")
        if not r.get("asset_id"): err("asset_id 없음")
        # asset_class
        ac = norm_class(r.get("asset_class"))
        if ac not in ASSET_CLASS_KO: err(f"미지원 asset_class: {r.get('asset_class')}")
        # type
        ty = norm_type(r.get("type"))
        if ty not in TYPE_KO: err(f"미지원 type: {r.get('type')}")
        # qty 양수
        q = r.get("qty","")
        if q in ("", None):
            if ty in ("OPEN_POS","BUY","SELL","GIFT_IN","GIFT_OUT","TRANSFER_IN","TRANSFER_OUT","SPLIT"):
                err(f"{ty}인데 qty 없음")
        elif not _num_ok(q): err(f"qty 숫자 아님: {q}")
        elif float(q) < 0: err(f"qty 음수 금지(부호는 type이 결정): {q}")
        # ccy
        if r.get("ccy") and r["ccy"] not in CCY_OK: err(f"ccy 오류(KRW/USD/BRL): {r['ccy']}")
        # 숫자형 컬럼 (amount/amount_ccy는 존재하는 쪽만 검사)
        for col in ("price", "fx", "amount", "amount_ccy", "fee", "tax"):
            if col in r and not _num_ok(r.get(col)):
                err(f"{col} 숫자/TODO 아님: {r.get(col)}")
        if _is_todo(r.get("fx")) or _is_todo(r.get("price")): n_todo += 1
        # fx_type
        fxt = (r.get("fx_type") or "").strip()
        if fxt and fxt not in FX_TYPE_KNOWN:
            warn(f"알 수 없는 fx_type: {fxt} (참고: {', '.join(sorted(x for x in FX_TYPE_KNOWN if x))})")
        if fxt in ("추정", "미상", "이동일"):
            n_lowconf += 1
        if r.get("ccy") not in (None, "", "KRW") and not r.get("fx") and not _is_todo(r.get("price")):
            warn("외화 거래인데 fx가 비어있음 — 세금/원가 계산에서 신뢰도 낮음으로 처리됩니다.")
        # 링크 필요
        if ty in ("TRANSFER_IN","TRANSFER_OUT") and not r.get("link_id"):
            warn(f"{ty}에 link_id 권장(대체 짝맞춤)")
    # 드라이런 재생 (음수현금·파싱 예외)
    dry = _dry_run(rows, header)
    warnings += dry.get("neg_cash", [])
    stats = dict(rows=len(rows), todo=n_todo, low_confidence_fx=n_lowconf,
                 owners=sorted({r.get("owner","") for r in rows if r.get("owner")}),
                 types=_count(rows,"type",norm_type), classes=_count(rows,"asset_class",norm_class))
    return dict(errors=errors, warnings=warnings, stats=stats)

def _count(rows, col, fn):
    from collections import Counter
    return dict(Counter(fn(r.get(col)) for r in rows))

def _dry_run(rows, header=None):
    """임시 폴더에 rows를 쓰고 Ledger로 재생해 음수현금/예외 탐지. 업로드 원본의 실제 컬럼 구성을 그대로 사용한다."""
    out = {"neg_cash": []}
    cols = header if header else (list(rows[0].keys()) if rows else KNOWN_COLS)
    tmp = Path(tempfile.mkdtemp())
    try:
        with open(tmp/"transactions.csv","w",encoding="utf-8-sig",newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols); w.writeheader()
            for r in rows: w.writerow({c:r.get(c,"") for c in cols})
        import importlib, ledger as _lg
        importlib.reload(_lg)
        L = _lg.Ledger(tmp)
        for w_ in L.warnings:
            if "음수 현금" in w_: out["neg_cash"].append(w_)
    except Exception as e:
        out["neg_cash"].append(f"드라이런 재생 실패(원장 구조 오류 가능): {e}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return out

def backup_and_replace(text, data_dir):
    """검증 통과한 원장 텍스트로 data/transactions.csv 교체 + 백업.
    반환: 백업경로."""
    from datetime import datetime
    data_dir = Path(data_dir)
    cur = data_dir / "transactions.csv"
    bdir = data_dir / "backups"; bdir.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = bdir / f"transactions_{stamp}.csv"
    if cur.exists():
        shutil.copy(cur, backup)
    cur.write_text(text if text.startswith("﻿") else text, encoding="utf-8-sig")
    return backup
