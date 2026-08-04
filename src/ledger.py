# -*- coding: utf-8 -*-
"""
ledger.py — 거래원장(transactions.csv) 재생 엔진 (SPEC 우선순위 1)
transactions.csv를 날짜순으로 replay하여 포지션·현금잔고·인컴·증여로트를 계산한다.

핵심 규칙(SPEC):
  · 수량은 항상 양수, 부호는 type이 결정.
  · OPEN_POS/OPEN_CASH = 기초잔고(현금 연동 없음).
  · BUY는 cash_account 현금을 반드시 자동 차감(1.45억 미스매치 재발 방지).
  · tag=HISTORY 행은 잔고 계산에서 제외(증여세 합산용 메타로만 보존).
  · fx=TODO / price=TODO 또는 fx_type∈{추정,미상} 은 에러가 아니라 '경고' → 세금계산 시 주의 표시.
  · 집계는 원장 원본 행에서만. 소계 행을 다시 더하지 않는다.
  · BALANCE 행 = 그 (owner,account,ccy)의 그 날짜 현금을 절대값으로 확정(override).
    같은 날짜에 여러 BALANCE 행이 있으면 합산(예: 예수금+외화RP). RP_BUY/RP_SELL/FX_BUY/FX_SELL은
    현금성 자산 '내부' 전환이며 최종 수치는 BALANCE가 담당하므로 현금에 반영하지 않는다(이중계상 방지).
  · amount 컬럼은 amount_ccy로 개명됨(구버전 amount도 하위호환 지원).
"""
import csv, re, shutil
from pathlib import Path
from datetime import date, datetime
from collections import defaultdict

from enums import norm_class, norm_type, class_ko, CASH_NOOP_TYPES
import profile as PROFILE

LOW_CONFIDENCE_FX_TYPES = {"추정", "미상", "이동일"}  # 세무상 취득환율로 쓰기엔 불확실

def _is_todo(x):
    return isinstance(x, str) and x.strip().upper() == "TODO"

def _num(x, default=0.0):
    if x is None or x == "" or _is_todo(x):
        return default
    try:
        return float(x)
    except (ValueError, TypeError):
        return default

def _get_amount(t, qty, price):
    """amount_ccy(신규) 우선, 없으면 amount(구버전) — 거래통화 기준 총액."""
    raw = t.get("amount_ccy")
    if raw in (None, ""):
        raw = t.get("amount")
    return _num(raw, qty * price)

_FX_FALLBACK_CACHE = {}
def _fallback_fx(ccy):
    """fx가 비어있는/TODO인 외화거래에 쓸 근사 환율. 1.0으로 두면 원화환산액이
    수백~수천분의 1로 왜곡되어(예: USD 거래를 1:1로 계산) 수익률이 터무니없이
    커지는 사고가 나므로, KRW가 아닌 통화는 절대 1.0을 쓰지 않는다."""
    if ccy == "KRW" or not ccy:
        return 1.0
    if ccy in _FX_FALLBACK_CACHE:
        return _FX_FALLBACK_CACHE[ccy]
    fx = None
    try:
        if ccy == "USD":
            import prices
            fx = prices.fx_usdkrw()
    except Exception:
        fx = None
    if not fx:
        # 최근 원장에 실제 기록된 값 근방의 근사치(정확한 값은 원장에 채우는 것이 우선)
        fx = {"USD": 1450.0, "BRL": 290.0}.get(ccy, 1.0)
    _FX_FALLBACK_CACHE[ccy] = fx
    return fx

def load_csv(path):
    with open(path, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))

def parse_note_meta(note):
    """note의 인라인 메타 파싱: carryover_expiry / donor_cost_basis / donor.
    key=value 형식(carryover_expiry=2027-05-18)을 우선 찾고, 없으면 자연어 표현
    ('이월과세: 2027-05-18 이전', '이월과세 만료 2027-06-10' 등)에서 날짜를 추출한다."""
    note = note or ""
    out = {}
    m = re.search(r"carryover_expiry=(\d{4}-\d{2}-\d{2})", note)
    if not m:
        m = re.search(r"이월과세[:\s]*(?:만료)?\s*(\d{4}-\d{2}-\d{2})", note)
    if m: out["carryover_expiry"] = m.group(1)
    m = re.search(r"donor_cost_basis=([\d.]+)", note)
    if m: out["donor_cost_basis"] = float(m.group(1))
    m = re.search(r"donor=([^\s|]+)", note)
    if m: out["donor"] = m.group(1)
    return out

def _bond_fx_settlement(note):
    """외화채권 BUY의 note에서 실제 결제통화·금액을 추출.
    'USD $9,605.32 결제' 우선, 없으면 'XX원 결제' 계열, 그것도 없으면
    '매수원금 18,433,312원'(KRW)로 폴백. 아무것도 못 찾으면 (None, None)."""
    note = note or ""
    m = re.search(r"USD\s*\$?\s*([\d,]+(?:\.\d+)?)\s*결제", note)
    if m:
        return "USD", float(m.group(1).replace(",", ""))
    m = re.search(r"([\d,]+(?:\.\d+)?)\s*원\s*결제", note)
    if m:
        return "KRW", float(m.group(1).replace(",", ""))
    m = re.search(r"매수원금\s*([\d,]+(?:\.\d+)?)\s*원", note)
    if m:
        return "KRW", float(m.group(1).replace(",", ""))
    return None, None

class Ledger:
    def __init__(self, data_dir=None, cost_method="AVG", txns=None, assets=None, accounts=None):
        """txns/assets/accounts를 직접 넘기면 파일을 다시 읽지 않는다 — 같은 원장을 여러
        시점(as-of date)으로 잘라 재생할 때(예: history_by_class) 파일 I/O 없이 재사용하기 위함.
        data_dir 미지정 시 현재 세션 프로필(profile.data_dir())을 사용."""
        self.data_dir = Path(data_dir) if data_dir else PROFILE.data_dir()
        self.cost_method = cost_method  # "AVG"(이동평균, 기본) — 향후 "FIFO" 확장 지점
        self.txns = txns if txns is not None else load_csv(self.data_dir / "transactions.csv")
        if assets is not None:
            self.assets = assets
        else:
            try:
                self.assets = {a["asset_id"]: a for a in load_csv(self.data_dir / "assets.csv")}
            except FileNotFoundError:
                self.assets = {}
        if accounts is not None:
            self.accounts = accounts
        else:
            try:
                self.accounts = {a["account"]: a for a in load_csv(self.data_dir / "accounts.csv")}
            except FileNotFoundError:
                self.accounts = {}
        self.warnings = []
        self.replay()

    def replay(self):
        pos = defaultdict(lambda: dict(qty=0.0, cost_native=0.0, cost_krw=0.0, realized_krw=0.0,
                                       ccy="KRW", asset_class="", carryover_expiry=None,
                                       donor_cost_basis=None, donor=None, gift_qty=0.0, has_todo=False))
        cash = defaultdict(float)          # (owner, account, ccy) -> amount
        income = []                        # 배당·이자·쿠폰
        realized = []                       # 매도 실현손익
        manual_price = {}                   # asset_id -> REVALUE/CORP_ACTION 단가
        manual_price_date = {}              # asset_id -> 그 단가를 마지막으로 갱신한 거래일
        gift_history = []                   # HISTORY 포함 모든 증여(증여세 합산용)
        balance_reset_state = {}            # (owner,account,ccy) -> 마지막으로 BALANCE 리셋한 날짜
        pending_subscribe = defaultdict(float)  # (owner,account,asset_id) -> 청약 후 미배정 금액(참고용)

        # BALANCE는 '그 날짜의 최종 확정 잔고'이므로, 같은 날짜 내에서는 txn_id 순서와 무관하게
        # 항상 마지막에 적용한다(먼저 적용되면 같은 날 뒤이은 BUY 등이 확정치를 다시 깎아버리는
        # 사고가 난다 — 배우자 RIA 현금 사례로 확인됨).
        def _order(x):
            return (x["date"], 1 if norm_type(x["type"]) == "BALANCE" else 0, x["txn_id"])
        for t in sorted(self.txns, key=_order):
            typ = norm_type(t["type"])
            acls = norm_class(t["asset_class"])
            owner, acct, aid = t["owner"], t["account"], t["asset_id"]
            ccy = (t.get("ccy") or "KRW").strip()
            tag = t.get("tag") or ""
            is_history = "HISTORY" in tag
            qty = _num(t["qty"]); price = _num(t["price"])
            fx_raw = t.get("fx")
            fx = _num(fx_raw, None)
            if not fx:
                fx = _fallback_fx(ccy)   # ★ 절대 1.0으로 떨어뜨리지 않는다(외화거래 원화환산 왜곡 방지)
            fx_type = (t.get("fx_type") or "").strip()
            amount = _get_amount(t, qty, price)
            fee = _num(t["fee"]); tax = _num(t["tax"])
            cash_acct = (t.get("cash_account") or acct)
            todo = _is_todo(fx_raw) or _is_todo(t.get("price"))
            # fx가 완전히 비어있는 외화거래 또는 fx_type이 추정/미상/이동일이면 '불확실'로 취급
            low_conf = fx_type in LOW_CONFIDENCE_FX_TYPES or ((fx_raw in (None, "")) and ccy != "KRW")
            note_meta = parse_note_meta(t.get("note", ""))

            # 모든 증여는 증여세 10년 합산 후보로 수집 (HISTORY 포함)
            if typ == "GIFT_IN":
                gift_history.append(dict(date=t["date"], owner=owner, asset_id=aid, qty=qty,
                                         price=price, ccy=ccy, amount=amount, tag=tag,
                                         note=t.get("note", ""), **note_meta))

            # HISTORY: 잔고에 영향 없음(증여세 합산 메타로만 보존)
            if is_history:
                continue

            # RP/외화 내부전환: 현금 무영향 (최종 수치는 BALANCE가 담당)
            if typ in CASH_NOOP_TYPES:
                continue

            P = pos[(owner, acct, aid)]
            # ccy/asset_class는 포지션의 정체성이라 BUY/OPEN_POS/증여/대체 등 '포지션을 만들거나
            # 옮기는' 거래에서만 갱신한다. DIVIDEND/INTEREST/COUPON/FEE/TAX/BALANCE는 이미 존재하는
            # 포지션에 대한 현금성 이벤트일 뿐이라 여기서 ccy를 건드리면, 예를 들어 USD 주식의
            # 배당을 원화로 환산해 ccy=KRW로 기록한 거래 한 줄이 그 주식의 통화를 뒤바꿔
            # 평가액 계산 시 환율 적용을 누락시키는 사고가 난다(실제 재현됨).
            if typ not in ("DIVIDEND", "INTEREST", "COUPON", "FEE", "TAX", "BALANCE"):
                P["ccy"] = ccy; P["asset_class"] = acls
            if todo or low_conf:
                P["has_todo"] = True
                kind = "TODO 미확정값" if todo else f"추정환율({fx_type or '미상'})"
                self.warnings.append(f"⚠️ {kind}: {t['txn_id']} {owner} {aid} — 세금/원가 계산에 참고용으로만 사용")

            if typ == "BALANCE":
                key = (owner, cash_acct, ccy)
                if balance_reset_state.get(key) != t["date"]:
                    cash[key] = 0.0
                    balance_reset_state[key] = t["date"]
                cash[key] += amount
                continue

            if acls == "CASH" and typ in ("TRANSFER_OUT", "TRANSFER_IN"):
                # 계좌간 현금 대체: 포지션이 아니라 현금 자체를 이동
                delta = -amount if typ == "TRANSFER_OUT" else amount
                cash[(owner, cash_acct, ccy)] += delta
                continue

            if typ == "FX_BUY":
                # 외화 매수: KRW를 내고 외화(ccy)를 사서 잔고에 편입
                cash[(owner, cash_acct, ccy)] += qty
                cash[(owner, cash_acct, "KRW")] -= amount
                continue
            if typ == "FX_SELL":
                # 외화 매도: 외화(ccy)를 팔아 KRW로 환전
                cash[(owner, cash_acct, ccy)] -= qty
                cash[(owner, cash_acct, "KRW")] += amount
                continue

            if typ in ("OPEN_POS", "BUY", "GIFT_IN", "TRANSFER_IN"):
                P["qty"] += qty
                P["cost_native"] += qty * price
                P["cost_krw"] += qty * price * fx
                if typ == "GIFT_IN":
                    P["gift_qty"] += qty
                    if note_meta.get("carryover_expiry"): P["carryover_expiry"] = note_meta["carryover_expiry"]
                    if note_meta.get("donor_cost_basis") is not None: P["donor_cost_basis"] = note_meta["donor_cost_basis"]
                    if note_meta.get("donor"): P["donor"] = note_meta["donor"]
                if typ == "BUY":
                    if acls == "BOND_FX":
                        # 외화채권(BRL 표시)은 실제 결제가 USD/KRW로 이뤄진다 — BRL은 채권
                        # 평가에만 쓰는 명목통화이지 사용자가 실제 보유한 현금이 아니다.
                        # note에서 실결제 통화·금액을 찾아 그쪽 현금을 차감한다(없으면 매수원금 KRW로 폴백).
                        settle_ccy, settle_amt = _bond_fx_settlement(t.get("note", ""))
                        if settle_amt is not None:
                            cash[(owner, cash_acct, settle_ccy)] -= (settle_amt + fee)
                        else:
                            self.warnings.append(f"⚠️ {t['txn_id']} {owner} {aid} — BOND_FX 매수의 실제 결제통화/금액을 "
                                                 f"note에서 찾지 못해 현금 차감을 건너뜀(대사 필요)")
                    else:
                        cash[(owner, cash_acct, ccy)] -= (amount + fee)   # ★ 현금 자동 차감

            elif typ == "OPEN_CASH":
                cash[(owner, cash_acct, ccy)] += amount

            elif typ in ("SELL", "GIFT_OUT", "TRANSFER_OUT"):
                if P["qty"] > 1e-12:
                    avg_native = P["cost_native"] / P["qty"]
                    avg_krw = P["cost_krw"] / P["qty"]
                    sell_q = min(qty, P["qty"])
                    if typ == "SELL":
                        pnl = (price - avg_native) * sell_q * fx - fee - tax
                        P["realized_krw"] += pnl
                        realized.append(dict(date=t["date"], settle_date=t.get("settle_date") or t["date"],
                                             owner=owner, account=acct, asset_id=aid, asset_class=acls,
                                             qty=sell_q, price=price, avg=avg_native, fx=fx, fee=fee, tax=tax,
                                             pnl_krw=pnl, ccy=ccy, carryover_expiry=P["carryover_expiry"],
                                             donor_cost_basis=P["donor_cost_basis"], note=t.get("note", ""),
                                             fx_type=fx_type, low_confidence=low_conf))
                        cash[(owner, cash_acct, ccy)] += (amount - fee - tax)
                        unit_native, unit_krw = avg_native, avg_krw
                    else:
                        # TRANSFER_OUT/GIFT_OUT: 이 행이 로트별 실제 취득단가(price)를 명시했다면
                        # 계좌 평균단가 대신 그 값을 우선 사용해 원가를 뗀다(이질적 로트가 섞인
                        # 풀에서 특정 로트만 이동/증여될 때, 평균단가로 떼면 남는 잔량의 원가가
                        # 왜곡된다 — 신한270-26 AAPL 사례로 확인됨).
                        if price > 0 and not todo:
                            unit_native, unit_krw = price, price * fx
                        else:
                            unit_native, unit_krw = avg_native, avg_krw
                    P["qty"] -= sell_q
                    P["cost_native"] -= unit_native * sell_q
                    P["cost_krw"] -= unit_krw * sell_q
                    if P["gift_qty"] > 0:
                        P["gift_qty"] = max(0.0, P["gift_qty"] - sell_q)

            elif typ == "DEPOSIT":
                cash[(owner, cash_acct, ccy)] += amount
            elif typ == "WITHDRAW":
                cash[(owner, cash_acct, ccy)] -= amount
            elif typ in ("DIVIDEND", "INTEREST", "COUPON"):
                amount_krw = amount * fx
                if acls == "BOND_FX" and ccy != "KRW":
                    # 외화채권 쿠폰: BRL은 명목통화일 뿐 실제로는 즉시 KRW로 환전 수령한다
                    # (note에 '원화 X원' 실수령액이 명시돼 있고 amount*fx가 그 값과 근접함).
                    cash[(owner, cash_acct, "KRW")] += (amount_krw - tax)
                else:
                    cash[(owner, cash_acct, ccy)] += (amount - tax)
                exempt = self.assets.get(aid, {}).get("tax_exempt", "N") == "Y"
                income.append(dict(date=t["date"], owner=owner, asset_id=aid, type=typ,
                                   amount_krw=amount_krw, tax_exempt=exempt))
            elif typ in ("FEE", "TAX"):
                cash[(owner, cash_acct, ccy)] -= amount
            elif typ == "FX":
                cash[(owner, cash_acct, ccy)] += amount
            elif typ == "SPLIT":
                P["qty"] *= (qty or 1.0)
            elif typ == "REVALUE":
                manual_price[aid] = price
                manual_price_date[aid] = t["date"]
                P["cost_native"] = price if not P["qty"] else P["cost_native"]
            elif typ == "CORP_ACTION":
                # 합병 등으로 취득단가만 재확정(수량·현금 불변). 총원가를 비례 유지해 KRW 원가를 보존.
                if P["qty"] > 1e-12:
                    new_native = qty * price if qty else P["qty"] * price
                    if P["cost_native"] > 0:
                        P["cost_krw"] *= (new_native / P["cost_native"])
                    P["cost_native"] = new_native
                manual_price[aid] = price
                manual_price_date[aid] = t["date"]
            elif typ == "SUBSCRIBE":
                # 청약 자금 납입: 현금만 먼저 차감(포지션은 이후 별도 OPEN_POS/배정 행에서 생성)
                cash[(owner, cash_acct, ccy)] -= amount
                pending_subscribe[(owner, acct, aid)] += amount
            # BALANCE/CASH_NOOP은 위에서 continue로 처리 완료

        self.positions = pos
        self.cash = cash
        self.income = income
        self.realized = realized
        self.manual_price = manual_price
        self.manual_price_date = manual_price_date
        self.gift_history = gift_history
        self.pending_subscribe = pending_subscribe
        self._check_negative_cash()

    def _check_negative_cash(self):
        for (o, acct, ccy), amt in self.cash.items():
            if amt < -1e-6:
                self.warnings.append(f"🔴 음수 현금잔고: {o} {acct} {ccy} = {amt:,.2f} (원장 누락 신호 — 대사 필요)")

    # ── 조회 헬퍼 ──
    def positions_list(self, owner=None, include_todo=True):
        out = []
        for (o, acct, aid), P in self.positions.items():
            if owner and o != owner: continue
            if abs(P["qty"]) < 1e-9: continue
            meta = self.assets.get(aid, {})
            out.append(dict(owner=o, account=acct, asset_id=aid,
                            name=meta.get("name_kr", aid), asset_class=P["asset_class"] or meta.get("asset_class",""),
                            price_source=meta.get("price_source", "manual"),
                            qty=P["qty"], avg_cost=P["cost_native"]/P["qty"] if P["qty"] else 0,
                            cost_krw=P["cost_krw"], ccy=P["ccy"], realized_krw=P["realized_krw"],
                            carryover_expiry=P["carryover_expiry"], donor_cost_basis=P["donor_cost_basis"],
                            donor=P["donor"], gift_qty=P["gift_qty"], has_todo=P["has_todo"],
                            revalue_price=self.manual_price.get(aid),
                            revalue_date=self.manual_price_date.get(aid)))
        return out

    def cash_list(self, owner=None):
        out = []
        for (o, acct, ccy), amt in self.cash.items():
            if owner and o != owner: continue
            if abs(amt) < 1e-6: continue
            out.append(dict(owner=o, account=acct, ccy=ccy, amount=amt))
        return out

    def owners(self):
        return sorted({t["owner"] for t in self.txns})

    def reconcile(self, owner, account, ccy, actual_balance):
        """증권사 앱 실제 현금잔고와 원장 계산값 대조. 차액 반환."""
        book = self.cash.get((owner, account, ccy), 0.0)
        return dict(owner=owner, account=account, ccy=ccy, book=book,
                    actual=actual_balance, diff=actual_balance - book)

    def class_cost_history(self, owner=None, fx_usd=None):
        """자산군별 취득원가(cost_krw) 누적 시계열 — 현황 탭의 누적면적그래프용.
        시세가 아니라 '그 시점까지 얼마를 투입/보유했는지'(원가 기준)이므로 과거 시세 조회가
        필요 없다 — 거래일마다 그 날짜까지의 거래만으로 원장을 다시 재생(replay)해 스냅샷을 뜬다.
        owner: None=전체 / 문자열=단일 / 리스트·집합=복수 소유자 합산.
        반환: [{date, asset_class, cost_krw}, ...] (long format, 오늘 날짜 스냅샷 포함)"""
        from datetime import date as _date
        if owner is None:
            match = lambda o: True
        elif isinstance(owner, (set, list, tuple)):
            s = set(owner); match = lambda o: o in s
        else:
            match = lambda o: o == owner
        dates = sorted({t["date"] for t in self.txns if t.get("date") and match(t["owner"])})
        if not dates:
            return []
        today_s = _date.today().isoformat()
        if dates[-1] != today_s:
            dates.append(today_s)

        out = []
        for d in dates:
            sub = [t for t in self.txns if t["date"] <= d]
            snap = Ledger(self.data_dir, txns=sub, assets=self.assets, accounts=self.accounts)
            by_class = defaultdict(float)
            for p in snap.positions_list():
                if not match(p["owner"]):
                    continue
                by_class[p["asset_class"] or "기타"] += p["cost_krw"]
            cash_fx = fx_usd or 1.0
            for c in snap.cash_list():
                if not match(c["owner"]):
                    continue
                by_class["CASH"] += c["amount"] * (cash_fx if c["ccy"] == "USD" else 1)
            for cls, v in by_class.items():
                if abs(v) > 1:
                    out.append(dict(date=d, asset_class=cls, cost_krw=v))
        return out


LEDGER_COLS = ["txn_id","date","settle_date","owner","account","asset_id","asset_class","type","qty",
               "price","ccy","fx","fx_type","amount_ccy","fee","tax","link_id","tag","note"]

def append_transaction(row, data_dir=None):
    """원장에 거래 1줄 추가 (대시보드 '거래 입력'용). 기존 파일의 실제 헤더를 따른다."""
    data_dir = Path(data_dir) if data_dir else PROFILE.data_dir()
    path = data_dir / "transactions.csv"
    exists = path.exists()
    cols = LEDGER_COLS
    if exists:
        with open(path, encoding="utf-8-sig") as f:
            header_line = f.readline().strip()
        if header_line:
            cols = header_line.lstrip("﻿").split(",")
    with open(path, "a", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        if not exists: w.writeheader()
        w.writerow({c: row.get(c, "") for c in cols})

def next_txn_id(date_str, data_dir=None):
    data_dir = Path(data_dir) if data_dir else PROFILE.data_dir()
    prefix = date_str.replace("-", "")
    try:
        rows = load_csv(data_dir / "transactions.csv")
    except FileNotFoundError:
        rows = []
    n = sum(1 for r in rows if r["txn_id"].startswith(prefix)) + 1
    return f"{prefix}-{n:03d}"

def _backup_ledger(data_dir=None):
    data_dir = Path(data_dir) if data_dir else PROFILE.data_dir()
    src = data_dir / "transactions.csv"
    if not src.exists():
        return None
    bdir = data_dir / "backups"
    bdir.mkdir(exist_ok=True)
    dst = bdir / f"transactions_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    shutil.copy(src, dst)
    return dst

def adjust_position(p, new_qty, new_avg_cost, data_dir=None):
    """현황 탭에서 종목별 수량·평단을 직접 고칠 때 쓰는 보정 함수.
    포지션(수량/평단)은 저장된 값이 아니라 거래들을 재생(replay)한 계산 결과이므로,
    값을 직접 덮어쓸 수 없다 — 대신 '기존 로트 전량 정리(TRANSFER_OUT) + 새 로트 개설
    (TRANSFER_IN)' 한 쌍을 원장에 기록해 같은 효과를 낸다.
      · TRANSFER는 현금·실현손익에 영향 없음(SELL이 아니므로 매도 취급 안 됨 → 양도세 미발생).
      · 평가액은 시세×환율의 계산 결과라 여기서 다루지 않는다(수량·평단만 보정 대상).
      · 두 거래 모두 기존 로트의 원화환산 비율(cost_krw/cost_native)을 그대로 써서
        KRW 원가도 오차 없이 승계한다.
    수정 전 원장은 data/backups/ 에 자동 백업된다."""
    qty, avg_native, cost_krw = p["qty"], p["avg_cost"], p["cost_krw"]
    if qty <= 1e-9 or avg_native <= 0:
        raise ValueError("현재 수량 또는 평단이 0이라 보정할 수 없습니다.")
    _backup_ledger(data_dir)
    today = date.today().isoformat()
    fx_used = (cost_krw / qty) / avg_native

    written = []
    out_id = next_txn_id(today, data_dir)
    out_row = dict(txn_id=out_id, date=today, settle_date="", owner=p["owner"], account=p["account"],
                   asset_id=p["asset_id"], asset_class=p["asset_class"], type="TRANSFER_OUT",
                   qty=qty, price=avg_native, ccy=p["ccy"], fx=round(fx_used, 6), fx_type="이동일",
                   amount_ccy=round(qty * avg_native, 4), fee="", tax="", link_id=out_id,
                   tag="ADJUST", note=f"수동 보정 — 기존 로트 정리 (수량 {qty:.4f}, 평단 {avg_native:.4f})")
    append_transaction(out_row, data_dir)
    written.append(out_row)

    if new_qty > 1e-9:
        in_id = next_txn_id(today, data_dir)
        in_row = dict(txn_id=in_id, date=today, settle_date="", owner=p["owner"], account=p["account"],
                      asset_id=p["asset_id"], asset_class=p["asset_class"], type="TRANSFER_IN",
                      qty=new_qty, price=new_avg_cost, ccy=p["ccy"], fx=round(fx_used, 6), fx_type="이동일",
                      amount_ccy=round(new_qty * new_avg_cost, 4), fee="", tax="", link_id=out_id,
                      tag="ADJUST", note=f"수동 보정 — 수정된 수량/평단 반영 (수량 {new_qty:.4f}, 평단 {new_avg_cost:.4f})")
        append_transaction(in_row, data_dir)
        written.append(in_row)
    return written

def set_manual_price(p, new_price, data_dir=None, as_of=None):
    """현황 탭에서 실시간 시세가 없는 종목의 현재가를 직접 고칠 때 쓰는 보정 함수.
    REVALUE 거래 1건을 원장에 추가한다 — 취득원가(cost_krw)는 건드리지 않고 평가에만 쓰인다.
    같은 asset_id에 이미 REVALUE 이력이 있으면 최신 날짜 것이 적용되므로, 그냥 새 행을 쌓으면 된다.
    수정 전 원장은 data/backups/ 에 자동 백업된다."""
    if new_price <= 0:
        raise ValueError("현재가는 0보다 커야 합니다.")
    _backup_ledger(data_dir)
    d = as_of or date.today().isoformat()
    txn_id = next_txn_id(d, data_dir)
    row = dict(txn_id=txn_id, date=d, settle_date="", owner=p["owner"], account=p["account"],
               asset_id=p["asset_id"], asset_class=p["asset_class"], type="REVALUE",
               qty="", price=new_price, ccy=p.get("ccy", "KRW"), fx="", fx_type="", amount_ccy="",
               fee="", tax="", link_id="", tag="", note=f"현황 탭 수동 현재가 갱신 → {new_price:,.4f}")
    append_transaction(row, data_dir)
    return row
