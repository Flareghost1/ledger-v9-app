# -*- coding: utf-8 -*-
"""
tax_rules.py — 세법 엔진 (SPEC §4, 구현 우선순위 3 · 돈이 가장 크게 걸린 부분)
  §4.1 이월과세 (증여 후 1년) — donor_cost_basis 소급 세금차액 포함
  §4.2 RIA 인출금지 (1년)
  §4.3 해외주식 양도세 (기본공제 250만, 22%)
  §4.4 금융소득종합과세 (연 2천만원 초과)
  §4.5 증여세 (10년 합산, 관계별 공제, 신고세액공제 3%)
세율·한도는 코드에 박아넣는다(대화로 설명하지 않는다).
"""
from datetime import date, datetime, timedelta
import calendar
from collections import defaultdict

import prices

CAPGAIN_DEDUCT = 2_500_000        # 해외주식 양도소득 기본공제(연)
CAPGAIN_RATE = 0.22               # 20% 국세 + 2% 지방세
FIN_INCOME_THRESHOLD = 20_000_000 # 금융소득종합과세 기준(연)

# ── §4.4+ 종합소득세 누진표 (v8: 비교과세 계산용) ──
# 2026년 기준 표준 구간. (상한, 세율, 누진공제) — 국세분. 지방세 10%는 별도 가산.
INCOME_TAX_BRACKETS = [
    (14_000_000, 0.06, 0),
    (50_000_000, 0.15, 1_260_000),
    (88_000_000, 0.24, 5_760_000),
    (150_000_000, 0.35, 15_440_000),
    (300_000_000, 0.38, 19_940_000),
    (500_000_000, 0.40, 25_940_000),
    (1_000_000_000, 0.42, 35_940_000),
    (float("inf"), 0.45, 65_940_000),
]
LOCAL_SURTAX = 0.10               # 지방소득세 = 국세의 10%
DIV_WITHHOLD_NATIONAL = 0.14      # 배당·이자 원천징수 국세분(지방세 1.4% 별도 → 합계 15.4%)
SEP_TAX_RATE = 0.154              # 분리과세 원천징수 합계(14% + 1.4%)

# ── §4.5 증여세 ──
GIFT_TAX_BRACKETS = [    # (상한, 세율, 누진공제)
    (100_000_000, 0.10, 0),
    (500_000_000, 0.20, 10_000_000),
    (1_000_000_000, 0.30, 60_000_000),
    (3_000_000_000, 0.40, 160_000_000),
    (float("inf"), 0.50, 460_000_000),
]
GIFT_REPORT_DISCOUNT = 0.03          # 신고세액공제(기한 내 신고)
GIFT_DEDUCT_SPOUSE = 600_000_000
GIFT_DEDUCT_ADULT = 50_000_000       # 성년 직계존비속(부모→성년자녀, 자녀→부모 공통)
GIFT_DEDUCT_MINOR = 20_000_000       # 미성년 직계비속
GIFT_DEDUCT_OTHER = 10_000_000       # 기타친족
MINOR_RECIPIENTS = {"장남", "차남"}   # ⚠️ 미성년자로 확인됨(사용자 확인, 2026-07-14) — 공제 2천만 적용
GIFT_FX_FALLBACK = 1520.4            # fx=TODO인 증여 건 근사 환율(동시기 실거래 기준, 추정치)

def _d(s):
    if isinstance(s, (date, datetime)):
        return s if isinstance(s, date) else s.date()
    try:
        return datetime.strptime(str(s)[:10], "%Y-%m-%d").date()
    except Exception:
        return None

def _add_years(d, years):
    try:
        return d.replace(year=d.year + years)
    except ValueError:
        return d.replace(month=2, day=28, year=d.year + years)

def _filing_deadline(gift_date):
    """증여일이 속한 달의 말일부터 3개월."""
    y, m = gift_date.year, gift_date.month
    mm, yy = m + 3, y
    while mm > 12:
        mm -= 12; yy += 1
    last_day = calendar.monthrange(yy, mm)[1]
    return date(yy, mm, last_day)

def _gift_tax_on(taxable):
    """누적 과세표준에 대한 산출세액(신고세액공제 전)."""
    if taxable <= 0:
        return 0.0
    for limit, rate, deduct in GIFT_TAX_BRACKETS:
        if taxable <= limit:
            return taxable * rate - deduct
    return taxable

# ── §4.1 이월과세 ──
def carryover_warnings(ledger, today=None):
    """증여받아 아직 이월과세 기간(1년) 내인 보유 포지션 경고.
    만료 전 매도하면 취득가가 증여자 평단(donor_cost_basis)으로 환원되어 양도세가 급증한다.
    가능하면 실제 세금차액(원)을 함께 계산해 보여준다."""
    today = _d(today) or date.today()
    fx = None
    out = []
    for p in ledger.positions_list():
        exp = _d(p.get("carryover_expiry"))
        if not (exp and p.get("gift_qty", 0) > 0 and today < exp):
            continue
        days = (exp - today).days
        qty = p["gift_qty"]
        donor_basis = p.get("donor_cost_basis")
        own_basis = p.get("avg_cost")
        basis_txt = f"${donor_basis:.2f}" if donor_basis is not None else "증여자 평단(원장에 미기재)"
        msg = (f"🔴 {p['owner']} {p['asset_id']} {qty:.0f}주 — 이월과세 만료 {exp.isoformat()} (D-{days}). "
               f"이 날짜 전 매도 시 취득가가 {basis_txt}으로 환원되어 양도세 급증.")
        if donor_basis is None:
            msg += " ⚠️ donor_cost_basis가 원장에 없어 세금차액은 계산하지 못했습니다."
        tax_now = tax_after = tax_diff = None
        if donor_basis is not None and own_basis:
            try:
                if fx is None:
                    fx = prices.fx_usdkrw()
                ticker = prices.ticker_of(p.get("price_source"))
                cur_price = prices.live_price(ticker) if ticker else None
                if cur_price:
                    gain_now = max(0.0, (cur_price - donor_basis) * qty * fx - CAPGAIN_DEDUCT)
                    gain_after = max(0.0, (cur_price - own_basis) * qty * fx - CAPGAIN_DEDUCT)
                    tax_now = gain_now * CAPGAIN_RATE
                    tax_after = gain_after * CAPGAIN_RATE
                    tax_diff = tax_now - tax_after
                    msg += (f" 지금 매도 시 예상양도세 ₩{tax_now:,.0f} vs 만료 후 매도 시 ₩{tax_after:,.0f} "
                           f"→ 지금 팔면 ₩{tax_diff:,.0f} 더 낸다.")
            except Exception:
                pass
        out.append(dict(owner=p["owner"], asset_id=p["asset_id"], qty=qty,
                        expiry=exp.isoformat(), days_left=days,
                        tax_if_now=tax_now, tax_if_after=tax_after, tax_diff=tax_diff, msg=msg))
    return out

# ── §4.2 RIA 인출금지 (1년) ──
def ria_status(ledger, today=None):
    """RIA 계좌: 마지막 매도일+1년 이전 인출은 전액 추징. 위반/해제 카운트다운."""
    today = _d(today) or date.today()
    ria_accts = {a["account"] for a in ledger.accounts.values() if "RIA" in a.get("account_type","") or "RIA_NO_WITHDRAW_1Y" in a.get("restrictions","")}
    # 명세서상 RIA 대상(배우자/장남/차남 AAPL 감면)도 감시 대상에 포함
    result = []
    violations = []
    for acct in sorted(ria_accts):
        sells = [t for t in ledger.txns if t["account"] == acct and t["type"] == "SELL"]
        withdraws = [t for t in ledger.txns if t["account"] == acct and t["type"] == "WITHDRAW"]
        last_sell = max((_d(t["date"]) for t in sells), default=None)
        unlock = _add_years(last_sell, 1) if last_sell else None
        for w in withdraws:
            wd = _d(w["date"])
            if last_sell and wd and wd < unlock:
                violations.append(dict(account=acct, txn_id=w["txn_id"], date=w["date"],
                                       msg=f"⛔ RIA 인출금지 위반: {acct} {w['txn_id']} ({w['date']}) — 전체 혜택 취소 + 추징 위험"))
        result.append(dict(account=acct, last_sell=last_sell.isoformat() if last_sell else None,
                           unlock=unlock.isoformat() if unlock else "매도 이력 없음",
                           days_to_unlock=(unlock - today).days if unlock else None))
    return dict(accounts=result, violations=violations)

# ── §4.3 해외주식 양도세 ──
def capital_gains(ledger, year=None):
    """연간 해외주식 실현손익 손익통산 → 양도세. 손실 종목은 절세매도 후보로 제시.
    귀속연도는 체결일(date)이 아니라 결제일(settle_date) 기준 — SPEC: 12월 말 매도는 익년 귀속 가능."""
    year = year or date.today().year
    def _tax_year_date(r):
        return _d(r.get("settle_date") or r["date"])
    us_lots = [r for r in ledger.realized
               if _tax_year_date(r) and _tax_year_date(r).year == year
               and ledger.assets.get(r["asset_id"], {}).get("asset_class") == "US_STOCK"]
    total_pnl = sum(r["pnl_krw"] for r in us_lots)
    taxable = max(0.0, total_pnl - CAPGAIN_DEDUCT)
    tax = taxable * CAPGAIN_RATE
    # 결제일이 체결일과 다른 해로 넘어가는 거래는 귀속연도 착오 위험 → 경고
    boundary = []
    for r in ledger.realized:
        d0, d1 = _d(r["date"]), _d(r.get("settle_date") or r["date"])
        if d0 and d1 and d0.year != d1.year:
            boundary.append(f"⚠️ {r['owner']} {r['asset_id']} 매도(체결 {r['date']} → 결제 {r.get('settle_date')}): "
                            f"양도세 귀속연도는 {d1.year}년(결제일 기준)입니다.")
    # 절세 매도 후보: 현재 평가손실(미실현) 종목 (손익통산용) — 시세 필요분은 대시보드에서 채움
    return dict(year=year, realized_pnl=total_pnl, deduct=CAPGAIN_DEDUCT,
                taxable=taxable, tax=tax, n_sells=len(us_lots), lots=us_lots,
                year_boundary_warnings=boundary)

# ── §4.4 금융소득종합과세 ──
def financial_income(ledger, year=None):
    """연간 배당+이자(비과세 제외) 집계 vs 2천만원 게이지."""
    year = year or date.today().year
    items = [i for i in ledger.income
             if _d(i["date"]) and _d(i["date"]).year == year and not i["tax_exempt"]]
    total = sum(i["amount_krw"] for i in items)
    return dict(year=year, total=total, threshold=FIN_INCOME_THRESHOLD,
                ratio=total / FIN_INCOME_THRESHOLD if FIN_INCOME_THRESHOLD else 0,
                over=total > FIN_INCOME_THRESHOLD, n=len(items))

# ── v8 §3: 금융소득 3분류 + 연말예상 + 비교과세 ──
def _progressive_tax(base):
    """종합소득 과세표준 → 국세 산출세액 (누진표)."""
    if base <= 0:
        return 0.0
    for limit, rate, deduct in INCOME_TAX_BRACKETS:
        if base <= limit:
            return base * rate - deduct
    return base * 0.45


def load_other_income(year, data_dir=None):
    """data/other_income.csv에서 해당 연도의 기타 종합소득(근로·사업·연금 등) 합계.
    반환: (합계원, 입력행 리스트). 미입력 연도는 (0, []) — 호출부에서 경고 표시."""
    import csv
    from pathlib import Path
    import profile as PROFILE
    data_dir = Path(data_dir) if data_dir else PROFILE.data_dir()
    path = data_dir / "other_income.csv"
    rows = []
    try:
        with open(path, encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                try:
                    if int(r.get("year", 0)) == year:
                        rows.append(r)
                except (ValueError, TypeError):
                    continue
    except FileNotFoundError:
        pass
    total = 0.0
    for r in rows:
        try:
            total += float(str(r.get("amount_krw", 0)).replace(",", "") or 0)
        except (ValueError, TypeError):
            continue
    return total, rows


def comprehensive_income_tax(other_income, fin_income, threshold=FIN_INCOME_THRESHOLD):
    """금융소득 2천만 초과분의 종합과세 추가납부세액 — 비교과세(2026-07-15 세션 검증 공식).
    산출세액(국세) = max[ 누진세(기타소득 + 금융소득 − 2천만) + 2천만×14%,
                         누진세(기타소득) + 금융소득×14% ]  ← 원천징수보다 덜 낼 수는 없음
    추가납부 = (산출세액 − 누진세(기타소득) − 금융소득×14%) × 1.1(지방세)  · 음수면 0."""
    if fin_income <= threshold:
        return dict(taxable_excess=0.0, extra_tax=0.0, method="분리과세로 종결",
                    other_income=other_income, fin_income=fin_income)
    general = _progressive_tax(other_income + fin_income - threshold) + threshold * DIV_WITHHOLD_NATIONAL
    floor_ = _progressive_tax(other_income) + fin_income * DIV_WITHHOLD_NATIONAL
    assessed = max(general, floor_)
    extra_national = assessed - _progressive_tax(other_income) - fin_income * DIV_WITHHOLD_NATIONAL
    extra_total = max(0.0, extra_national) * (1 + LOCAL_SURTAX)
    return dict(taxable_excess=fin_income - threshold, extra_tax=extra_total,
                method="일반산출" if general >= floor_ else "비교과세 하한",
                other_income=other_income, fin_income=fin_income)


def financial_income_full(ledger, positions=None, fx=None, today=None,
                          threshold=FIN_INCOME_THRESHOLD, other_income=None):
    """v8 세금리포트용: 금융소득 3분류(비과세/분리과세/종합과세) × (YTD/연말예상) + 추가납부세액.
    연말예상 = YTD 실현 + 잔여 지급월 예상(cashflow.INCOME_TABLE 스케줄 재사용).
    other_income=None이면 data/other_income.csv에서 자동 로드."""
    today = _d(today) or date.today()
    year = today.year

    ytd_exempt = ytd_taxable = 0.0
    for i in ledger.income:
        d = _d(i["date"])
        if not d or d.year != year:
            continue
        if i["tax_exempt"]:
            ytd_exempt += i["amount_krw"]
        else:
            ytd_taxable += i["amount_krw"]

    # 잔여 예상: 배당지급월 스케줄에서 오늘 이후 월 분만 합산 (트렌드/현금흐름탭과 동일 데이터)
    est_rest_exempt = est_rest_taxable = 0.0
    if positions is not None and fx is not None:
        import cashflow
        cf = cashflow.project(positions, fx, lambda p: p.get("_v", p.get("cost_krw", 0)))
        for r in cf["rows"]:
            if not r["months"]:
                continue  # 만기/일시(ELB 등)는 지급 시점 불확실 → 연말예상에서 제외
            per = r["annual"] / len(r["months"])
            rest = sum(per for m in r["months"] if m > today.month)
            if r["tax_exempt"]:
                est_rest_exempt += rest
            else:
                est_rest_taxable += rest

    est_exempt = ytd_exempt + est_rest_exempt
    est_taxable = ytd_taxable + est_rest_taxable

    if other_income is None:
        other_income, other_rows = load_other_income(year)
    else:
        other_rows = None
    comp = comprehensive_income_tax(other_income, est_taxable, threshold)

    def _split(taxable):
        return min(taxable, threshold), max(0.0, taxable - threshold)

    ytd_sep, ytd_comp = _split(ytd_taxable)
    est_sep, est_comp = _split(est_taxable)
    return dict(
        year=year, threshold=threshold,
        ytd=dict(exempt=ytd_exempt, separate=ytd_sep, comprehensive=ytd_comp, taxable=ytd_taxable),
        est=dict(exempt=est_exempt, separate=est_sep, comprehensive=est_comp, taxable=est_taxable),
        other_income=other_income, other_income_rows=other_rows,
        other_income_missing=(other_income == 0),
        extra_tax=comp["extra_tax"], comp_method=comp["method"],
        ratio=ytd_taxable / threshold if threshold else 0,
        est_ratio=est_taxable / threshold if threshold else 0,
        over=ytd_taxable > threshold, est_over=est_taxable > threshold,
    )


# ── §4.5 증여세 (10년 합산) ──
def _gift_deduction(recipient):
    if recipient == "배우자":
        return GIFT_DEDUCT_SPOUSE
    if recipient in MINOR_RECIPIENTS:
        return GIFT_DEDUCT_MINOR
    if recipient in ("장남", "차남", "부친", "모친"):
        return GIFT_DEDUCT_ADULT
    return GIFT_DEDUCT_OTHER

def _deduction_label(recipient, deduction):
    """실제 적용된 공제액을 그대로 라벨화(하드코딩 텍스트가 deduction과 어긋나지 않도록)."""
    if deduction == GIFT_DEDUCT_SPOUSE:
        return f"배우자({deduction//100_000_000}억공제)"
    if deduction == GIFT_DEDUCT_MINOR:
        return "미성년 직계비속(2천만공제)"
    if deduction == GIFT_DEDUCT_ADULT:
        return "성년 직계존비속(5천만공제)"
    return "기타친족(1천만공제)"

def _gift_krw_value(g):
    """증여 1건의 원화환산 가치. fx=TODO(donor 메타에 없음)면 근사환율 사용, estimated=True로 표시."""
    amount = g.get("amount")
    if amount is None:
        amount = (g.get("qty") or 0) * (g.get("price") or 0)
    if g.get("ccy", "KRW") == "KRW":
        return float(amount), False
    return float(amount) * GIFT_FX_FALLBACK, True

def gift_tax_summary(ledger, ref_date=None, window_years=10):
    """수증자별 10년 합산 증여세. donor 기본값=본인. 미성년(MINOR_RECIPIENTS)은 공제 2천만.
    각 증여 건마다 누적과세 재계산 후 기납부세액공제(직전 누적세액 차감) + 신고세액공제 3%."""
    ref_date = _d(ref_date) or date.today()
    groups = defaultdict(list)
    for g in getattr(ledger, "gift_history", []):
        donor = g.get("donor") or "본인"
        groups[(donor, g["owner"])].append(g)

    results = []
    for (donor, recipient), gifts in groups.items():
        gifts_sorted = sorted(gifts, key=lambda x: x["date"])
        deduction = _gift_deduction(recipient)
        cum = 0.0
        prior_tax = 0.0
        timeline = []
        has_estimate = False
        for g in gifts_sorted:
            krw, estimated = _gift_krw_value(g)
            has_estimate = has_estimate or estimated
            cum += krw
            taxable = max(0.0, cum - deduction)
            tax_cum = _gift_tax_on(taxable)
            tax_this_gross = max(0.0, tax_cum - prior_tax)     # 기납부세액공제
            tax_this_net = tax_this_gross * (1 - GIFT_REPORT_DISCOUNT)
            timeline.append(dict(date=g["date"], asset_id=g["asset_id"], krw=krw, estimated=estimated,
                                 cumulative=cum, taxable=taxable, tax_cum=tax_cum,
                                 tax_this_gross=tax_this_gross, tax_this_net=tax_this_net,
                                 is_history="HISTORY" in (g.get("tag") or "")))
            prior_tax = tax_cum
        last = gifts_sorted[-1]
        last_date = _d(last["date"])
        deadline = _filing_deadline(last_date)
        latest = timeline[-1] if timeline else {}
        results.append(dict(
            donor=donor, recipient=recipient, deduction=deduction,
            minor=_deduction_label(recipient, deduction),
            cumulative=cum, taxable=latest.get("taxable", 0), tax_total=prior_tax,
            tax_due_net=latest.get("tax_this_net", 0), filing_deadline=deadline.isoformat(),
            days_left=(deadline - ref_date).days, filed=(ref_date > deadline),
            has_estimate=has_estimate, timeline=timeline,
        ))
    return sorted(results, key=lambda r: r["days_left"])

def summary(ledger, today=None):
    """리포트·대시보드용 세금 요약 묶음."""
    return dict(
        carryover=carryover_warnings(ledger, today),
        ria=ria_status(ledger, today),
        capgains=capital_gains(ledger),
        fin_income=financial_income(ledger),
        gift_tax=gift_tax_summary(ledger, today),
    )
