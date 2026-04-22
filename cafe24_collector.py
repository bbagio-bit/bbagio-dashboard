#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BBagio Cafe24 자사몰 데이터 수집기
- OAuth 2.0 인증 (최초 1회 수동, 이후 자동 갱신)
- 수집 항목: 매출(일별), 신규고객, 상품별/옵션별 성과, 일별 상품 드릴다운
- 결과: cafe24_latest.json → GitHub 업로드
"""

import os as _os
import re
import json
import shutil
import base64
import urllib.request
import urllib.parse
import urllib.error
import webbrowser
from pathlib import Path
from datetime import datetime, timedelta

# ──────────────────────────────────────────────
# 설정 로드
# ──────────────────────────────────────────────
_dir = Path(__file__).parent
cfg_path = _dir / "config.json"
cfg = {}
if cfg_path.exists():
    with open(cfg_path, "r", encoding="utf-8") as f:
        cfg = json.load(f)

def _env(key, cfg_key=None, default=""):
    if cfg_key is None:
        cfg_key = key.lower()
    return _os.environ.get(key) or cfg.get(cfg_key, default)

MALL_ID       = _env("CAFE24_MALL_ID",       "cafe24_mall_id")   or "bionex"
CLIENT_ID     = _env("CAFE24_CLIENT_ID",     "cafe24_client_id")
CLIENT_SECRET = _env("CAFE24_CLIENT_SECRET", "cafe24_client_secret")
ACCESS_TOKEN  = _env("CAFE24_ACCESS_TOKEN",  "cafe24_access_token")
REFRESH_TOKEN = _env("CAFE24_REFRESH_TOKEN", "cafe24_refresh_token")
GH_TOKEN      = _env("GH_TOKEN",            "github_token")
GH_USER       = _env("GH_USER",             "github_user")
GH_REPO       = _env("GH_REPO",             "github_repo")
_is_ci = _os.environ.get("CI") == "true"

REDIRECT_URI = "https://bionex.cafe24.com/"
API_BASE     = f"https://{MALL_ID}.cafe24api.com/api/v2"
API_VERSION  = "2026-03-01"
SCOPES       = "mall.read_order,mall.read_salesreport,mall.read_customer,mall.read_product,mall.read_analytics,mall.read_category"

OUTPUT_DIR = _dir
TOKEN_FILE = _dir / "cafe24_tokens.json"


# ──────────────────────────────────────────────
# 토큰 저장/로드
# ──────────────────────────────────────────────
def _save_tokens(access, refresh):
    # 토큰은 cafe24_tokens.json에만 저장 (config.json은 건드리지 않음)
    data = {"access_token": access, "refresh_token": refresh, "saved_at": datetime.now().isoformat()}
    with open(TOKEN_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print("  토큰 저장 완료")


def _load_tokens():
    global ACCESS_TOKEN, REFRESH_TOKEN
    if TOKEN_FILE.exists():
        with open(TOKEN_FILE, "r", encoding="utf-8") as f:
            t = json.load(f)
        ACCESS_TOKEN  = t.get("access_token", ACCESS_TOKEN)
        REFRESH_TOKEN = t.get("refresh_token", REFRESH_TOKEN)
    return ACCESS_TOKEN, REFRESH_TOKEN


# ──────────────────────────────────────────────
# OAuth 인증
# ──────────────────────────────────────────────
def _do_oauth():
    auth_url = (
        f"https://{MALL_ID}.cafe24api.com/api/v2/oauth/authorize"
        f"?response_type=code"
        f"&client_id={CLIENT_ID}"
        f"&state=bbagio_secure"
        f"&redirect_uri={urllib.parse.quote(REDIRECT_URI, safe='')}"
        f"&scope={urllib.parse.quote(SCOPES, safe='')}"
    )
    print("\n" + "="*60)
    print("[인증 필요] Cafe24 OAuth 인증")
    print("="*60)
    print(f"\n아래 URL을 브라우저에서 열어 bionex 관리자로 로그인 후 승인하세요:\n")
    print(auth_url)
    print()
    if not _is_ci:
        webbrowser.open(auth_url)
        print("승인 후 리다이렉트된 전체 URL을 붙여넣으세요:")
        redirect = input("> ").strip()
        parsed = urllib.parse.urlparse(redirect)
        params = urllib.parse.parse_qs(parsed.query)
        code = params.get("code", [None])[0]
        if not code:
            raise ValueError("URL에서 code를 찾을 수 없습니다.")
        _exchange_code(code)
    else:
        raise RuntimeError("CI 환경에서 최초 인증 불가.")


def _exchange_code(code):
    url = f"{API_BASE}/oauth/token"
    creds = base64.b64encode(f"{CLIENT_ID}:{CLIENT_SECRET}".encode()).decode()
    data = urllib.parse.urlencode({
        "grant_type":   "authorization_code",
        "code":         code,
        "redirect_uri": REDIRECT_URI,
    }).encode()
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Authorization", f"Basic {creds}")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    with urllib.request.urlopen(req) as r:
        result = json.loads(r.read())
    _save_tokens(result["access_token"], result["refresh_token"])
    return result["access_token"], result["refresh_token"]


def _refresh_access_token(refresh_token):
    url = f"{API_BASE}/oauth/token"
    creds = base64.b64encode(f"{CLIENT_ID}:{CLIENT_SECRET}".encode()).decode()
    data = urllib.parse.urlencode({
        "grant_type":    "refresh_token",
        "refresh_token": refresh_token,
    }).encode()
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Authorization", f"Basic {creds}")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with urllib.request.urlopen(req) as r:
            result = json.loads(r.read())
        _save_tokens(result["access_token"], result["refresh_token"])
        print("  Access Token 갱신 완료")
        return result["access_token"], result["refresh_token"]
    except urllib.error.HTTPError as e:
        print(f"  토큰 갱신 실패: {e.code}")
        return None, None


def _get_valid_token():
    access, refresh = _load_tokens()
    if not access and not refresh:
        _do_oauth()
        return _load_tokens()[0]
    if refresh:
        new_access, _ = _refresh_access_token(refresh)
        if new_access:
            return new_access
        # refresh_token도 만료 → 재인증 필요
        print("  ⚠️  Refresh token 만료. 브라우저 재인증을 시작합니다...")
        _do_oauth()
        return _load_tokens()[0]
    if access:
        print("  (refresh token 없음, 기존 access_token 사용)")
        return access
    _do_oauth()
    return _load_tokens()[0]


# ──────────────────────────────────────────────
# API 헬퍼
# ──────────────────────────────────────────────
def _api_get(endpoint, token, params=None):
    url = f"{API_BASE}/{endpoint}"
    if params:
        url += "?" + urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
    req = urllib.request.Request(url)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Content-Type",  "application/json")
    req.add_header("X-Cafe24-Api-Version", API_VERSION)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        print(f"  API 오류 {e.code} [{endpoint}]: {body[:200]}")
        return {}
    except Exception as ex:
        print(f"  요청 오류 [{endpoint}]: {ex}")
        return {}


def _parse_option(raw):
    """option_value 필드 → 문자열 옵션명"""
    if not raw:
        return ""
    if isinstance(raw, (list, dict)):
        return str(raw)
    return str(raw).strip()


# ──────────────────────────────────────────────
# 핵심 수집: 단일 패스로 모든 데이터 집계
# ──────────────────────────────────────────────
def collect_all(token, start_date, end_date):
    """
    주문 1회 순회로 다음을 동시 집계:
      - daily:          일별 {orders, revenue, new_customers, canceled, member_orders, nonmember_orders}
      - products:       상품별 {name, qty, revenue, options, daily_qty}
      - options:        옵션별 전체 집계 (상품명 포함)
      - daily_products: 날짜 → [{product_name, option_name, qty, revenue}]
      - hourly:         시간대별 {orders, revenue} (0~23시)
      - member_stats:   {member: {orders, revenue}, nonmember: {orders, revenue}}
    """
    print("  주문 데이터 수집 중 (단일 패스)...")

    daily         = {}   # date → stats
    product_stats = {}   # pid  → stats
    option_stats  = {}   # "pid::oname" → stats
    daily_products = {}  # date → list of {product_name, option_name, qty, revenue}
    hourly        = {str(h): {"orders": 0, "revenue": 0.0} for h in range(24)}
    member_stats  = {
        "member":    {"orders": 0, "revenue": 0.0},
        "nonmember": {"orders": 0, "revenue": 0.0},
    }

    page = 1
    while True:
        data = _api_get("admin/orders", token, {
            "start_date": start_date,
            "end_date":   end_date,
            "embed":      "items",
            "limit":      100,
            "offset":     (page - 1) * 100,
        })
        orders = data.get("orders", [])
        if not orders:
            break

        for o in orders:
            raw_date = o.get("order_date", "")
            date = raw_date[:10] if raw_date else "unknown"

            # ── 일별 초기화
            if date not in daily:
                daily[date] = {
                    "orders": 0, "revenue": 0.0,
                    "new_customers": 0, "canceled": 0,
                    "member_orders": 0, "nonmember_orders": 0,
                    "coupon_discount": 0.0,
                    "mileage_used": 0.0,
                    "hourly_orders":  {str(h): 0   for h in range(24)},
                    "hourly_revenue": {str(h): 0.0 for h in range(24)},
                }
            if date not in daily_products:
                daily_products[date] = []

            # ── 취소 처리
            if o.get("canceled") == "T":
                daily[date]["canceled"] += 1
                continue

            # ── 매출 + 할인
            amt     = o.get("actual_order_amount") or o.get("initial_order_amount") or {}
            revenue = float(amt.get("payment_amount", 0) or 0)
            coupon  = float(amt.get("coupon_discount_price", 0) or 0)
            mileage = float(amt.get("point_amount_to_pay", 0) or 0)
            daily[date]["orders"]          += 1
            daily[date]["revenue"]         += revenue
            daily[date]["coupon_discount"] += coupon
            daily[date]["mileage_used"]    += mileage
            if o.get("first_order") == "T":
                daily[date]["new_customers"] += 1

            # ── 시간대별 (글로벌 + 일별)
            try:
                hour = str(int(raw_date[11:13])) if len(raw_date) >= 13 else "0"
                if hour in hourly:
                    hourly[hour]["orders"]  += 1
                    hourly[hour]["revenue"] += revenue
                if hour in daily[date]["hourly_orders"]:
                    daily[date]["hourly_orders"][hour]  += 1
                    daily[date]["hourly_revenue"][hour] += revenue
            except Exception:
                pass

            # ── 회원/비회원
            is_member = bool(o.get("member_id"))
            if is_member:
                daily[date]["member_orders"] += 1
                member_stats["member"]["orders"]  += 1
                member_stats["member"]["revenue"] += revenue
            else:
                daily[date]["nonmember_orders"] += 1
                member_stats["nonmember"]["orders"]  += 1
                member_stats["nonmember"]["revenue"] += revenue

            # ── 상품/옵션 집계
            items = o.get("items", [])
            # 상품 수가 여러 개면 매출을 item 단가 기준으로 분할
            for item in items:
                pid   = str(item.get("product_no", ""))
                pname = item.get("product_name", "알 수 없음") or "알 수 없음"
                oname = _parse_option(item.get("option_value"))
                qty   = int(item.get("quantity", 0) or 0)
                price_each = float(item.get("product_price", 0) or 0)
                item_rev = price_each * qty

                # 상품 집계
                if pid not in product_stats:
                    product_stats[pid] = {
                        "product_no":   pid,
                        "product_name": pname,
                        "quantity":     0,
                        "revenue":      0.0,
                        "options":      {},
                        "daily":        {},   # date → qty
                    }
                product_stats[pid]["quantity"] += qty
                product_stats[pid]["revenue"]  += item_rev
                product_stats[pid]["daily"][date] = product_stats[pid]["daily"].get(date, 0) + qty

                # 옵션 집계 (상품별)
                if oname:
                    opts = product_stats[pid]["options"]
                    if oname not in opts:
                        opts[oname] = {"option_name": oname, "quantity": 0, "revenue": 0.0}
                    opts[oname]["quantity"] += qty
                    opts[oname]["revenue"]  += item_rev

                # 전체 옵션 집계
                okey = f"{pid}::{oname}"
                if okey not in option_stats:
                    option_stats[okey] = {
                        "product_name": pname,
                        "option_name":  oname or "(옵션 없음)",
                        "quantity":     0,
                        "revenue":      0.0,
                    }
                option_stats[okey]["quantity"] += qty
                option_stats[okey]["revenue"]  += item_rev

                # 일별 상품 드릴다운 (집계)
                # 같은 날 같은 상품+옵션은 합산
                found = False
                for entry in daily_products[date]:
                    if entry["product_name"] == pname and entry["option_name"] == (oname or "(옵션 없음)"):
                        entry["quantity"] += qty
                        entry["revenue"]  += item_rev
                        found = True
                        break
                if not found:
                    daily_products[date].append({
                        "product_name": pname,
                        "option_name":  oname or "(옵션 없음)",
                        "quantity":     qty,
                        "revenue":      item_rev,
                    })

        if len(orders) < 100:
            break
        page += 1

    # ── 정렬
    sorted_products = sorted(product_stats.values(), key=lambda x: x["revenue"], reverse=True)
    for p in sorted_products:
        p["options"] = sorted(p["options"].values(), key=lambda x: x["quantity"], reverse=True)

    sorted_options = sorted(option_stats.values(), key=lambda x: x["revenue"], reverse=True)

    # daily_products도 매출순 정렬
    for date in daily_products:
        daily_products[date].sort(key=lambda x: x["revenue"], reverse=True)

    return daily, sorted_products, sorted_options, daily_products, hourly, member_stats


# ──────────────────────────────────────────────
# GitHub 업로드
# ──────────────────────────────────────────────
def upload_to_github(file_path, gh_filename, token, user, repo, branch="main"):
    if not token or not user or not repo:
        print(f"  GitHub 설정 없음 — {gh_filename} 스킵")
        return False
    with open(file_path, "rb") as f:
        content_b64 = base64.b64encode(f.read()).decode()
    api_url = f"https://api.github.com/repos/{user}/{repo}/contents/{gh_filename}"
    headers = {
        "Authorization": f"token {token}",
        "Accept":        "application/vnd.github+json",
        "Content-Type":  "application/json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    get_req = urllib.request.Request(api_url + f"?ref={branch}", headers=headers)
    sha = None
    try:
        with urllib.request.urlopen(get_req) as r:
            sha = json.loads(r.read()).get("sha")
    except urllib.error.HTTPError:
        pass
    body = {
        "message": f"[자동] Cafe24 데이터 {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "content": content_b64,
        "branch":  branch,
    }
    if sha:
        body["sha"] = sha
    put_req = urllib.request.Request(
        api_url, data=json.dumps(body).encode(), method="PUT", headers=headers)
    try:
        with urllib.request.urlopen(put_req) as r:
            print(f"  GitHub 업로드 완료 ({branch}): {gh_filename}")
            return True
    except urllib.error.HTTPError as e:
        print(f"  GitHub 업로드 실패 ({e.code}): {e.read().decode()[:200]}")
        return False


# ──────────────────────────────────────────────
# 메인
# ──────────────────────────────────────────────
def main():
    print("\n" + "="*60)
    print("BBagio Cafe24 자사몰 데이터 수집 시작")
    print("="*60)

    token = _get_valid_token()
    if not token:
        print("유효한 토큰을 얻지 못했습니다.")
        return

    today      = datetime.now()
    days_back  = int(cfg.get("days_back", 90))   # 3개월치 수집
    start_date = (today - timedelta(days=days_back)).strftime("%Y-%m-%d")
    end_date   = today.strftime("%Y-%m-%d")
    print(f"수집 기간: {start_date} ~ {end_date} ({days_back}일)")

    # 단일 패스 수집
    daily_data, products, options, daily_products, hourly, member_stats = collect_all(token, start_date, end_date)

    # 요약
    total_revenue       = sum(d["revenue"]       for d in daily_data.values())
    total_orders        = sum(d["orders"]        for d in daily_data.values())
    total_new_customers = sum(d["new_customers"] for d in daily_data.values())
    total_canceled      = sum(d["canceled"]      for d in daily_data.values())

    result = {
        "collected_at": today.strftime("%Y-%m-%d %H:%M:%S"),
        "mall_id":      MALL_ID,
        "period":       {"start": start_date, "end": end_date, "days": days_back},
        "summary": {
            "total_revenue":   round(total_revenue, 0),
            "total_orders":    total_orders,
            "avg_order_value": round(total_revenue / total_orders, 0) if total_orders > 0 else 0,
            "new_customers":   total_new_customers,
            "canceled_orders": total_canceled,
            "top_product":     products[0]["product_name"] if products else "-",
        },
        "daily": {
            date: {
                "orders":           d["orders"],
                "revenue":          round(d["revenue"], 0),
                "new_customers":    d["new_customers"],
                "canceled":         d["canceled"],
                "member_orders":    d.get("member_orders", 0),
                "nonmember_orders": d.get("nonmember_orders", 0),
                "coupon_discount":  round(d.get("coupon_discount", 0), 0),
                "mileage_used":     round(d.get("mileage_used", 0), 0),
                "hourly_orders":    {h: round(v,0) for h,v in d.get("hourly_orders",{}).items()},
                "hourly_revenue":   {h: round(v,0) for h,v in d.get("hourly_revenue",{}).items()},
            }
            for date, d in sorted(daily_data.items())
        },
        "products":        products,
        "options":         options,
        "daily_products":  daily_products,
        "hourly": {
            h: {"orders": v["orders"], "revenue": round(v["revenue"], 0)}
            for h, v in sorted(hourly.items(), key=lambda x: int(x[0]))
        },
        "member_stats": {
            "member":    {"orders": member_stats["member"]["orders"],    "revenue": round(member_stats["member"]["revenue"], 0)},
            "nonmember": {"orders": member_stats["nonmember"]["orders"], "revenue": round(member_stats["nonmember"]["revenue"], 0)},
        },
    }

    # ── 공구매출(group_revenue) 계산 ────────────────────────────────
    # config.json의 group_purchase_keyword로 상품명 필터링
    _grp_kw = cfg.get("group_purchase_keyword", "공동구매")
    for _date, _prods in daily_products.items():
        _grp = sum(p.get("revenue", 0) for p in _prods
                   if _grp_kw in (p.get("product_name") or ""))
        if _date in result["daily"]:
            result["daily"][_date]["group_revenue"] = int(_grp)
    if any(result["daily"][d].get("group_revenue", 0) > 0 for d in result["daily"]):
        print(f"  ✅ 공구매출 집계 완료 (키워드: '{_grp_kw}')")
    else:
        print(f"  ⚠️  공구매출 0원 — 상품명에 '{_grp_kw}' 포함 항목 없음 (config.json의 group_purchase_keyword 확인)")

    # ── 월별 목표매출 로드 ───────────────────────────────────────────
    # 우선순위: BBagio_자사몰_월별목표.xlsx > config.json의 cafe24_monthly_targets
    def _load_monthly_targets() -> dict:
        targets = dict(cfg.get("cafe24_monthly_targets", {}))
        target_file = _dir / "BBagio_자사몰_월별목표.xlsx"
        if not target_file.exists():
            return targets
        try:
            import openpyxl
            wb = openpyxl.load_workbook(str(target_file), data_only=True)
            ws = wb.active
            for row in ws.iter_rows(min_row=2, values_only=True):
                if not row or row[0] is None or row[1] is None or row[2] is None:
                    continue
                try:
                    year  = int(str(row[0]).split('.')[0].strip())
                    month = int(row[1])
                    tgt   = int(float(str(row[2]).replace(',', '')))
                    targets[f"{year:04d}-{month:02d}"] = tgt
                except Exception:
                    pass
        except Exception as e:
            print(f"  ⚠️  월별목표 엑셀 로드 실패: {e}")
        return targets

    result["monthly_targets"] = _load_monthly_targets()

    out_path = OUTPUT_DIR / "cafe24_latest.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)

    print(f"\n✅ 수집 완료: {out_path}")
    print(f"   총 매출:  {int(total_revenue):,}원")
    print(f"   주문건:   {total_orders}건 (취소 {total_canceled}건)")
    print(f"   신규고객: {total_new_customers}명")
    print(f"   상품:     {len(products)}개 | 옵션: {len(options)}개")

    # ── cafe24_data.json 생성 (HTML은 fetch로 로드하는 구조) ─────────
    def _extract_meta_from_html(html_path):
        """BBagio_meta_dashboard.html 의 const DATA = {...}; 에서 메타 데이터 추출"""
        if not html_path.exists():
            return None
        try:
            html = html_path.read_bytes().decode("utf-8", errors="replace")
            m = re.search(r'const DATA\s*=\s*(\{[\s\S]*?\});\s*\n', html)
            if m:
                return json.loads(m.group(1))
        except Exception:
            pass
        return None

    # 메타 광고 데이터 로드 (4단계 fallback)
    # ★ output/ 먼저 확인: meta_collector.py가 run_all.bat에서 먼저 실행되어
    #   output/meta_summary.json을 최신화한 경우 그 파일을 우선 사용.
    #   root의 meta_summary.json은 이전 실행 때 복사된 오래된 파일일 수 있음.
    meta_summary = None
    for mp in [_dir/"output"/"meta_summary.json", OUTPUT_DIR/"meta_summary.json", _dir/"meta_summary.json"]:
        if mp.exists():
            try:
                meta_summary = json.loads(mp.read_text(encoding="utf-8"))
                print(f"  ✅ meta_summary.json 로드: {mp}")
                break
            except Exception:
                pass
    if not meta_summary:
        for hp in [_dir/"output"/"BBagio_meta_dashboard.html", OUTPUT_DIR/"BBagio_meta_dashboard.html", _dir/"BBagio_meta_dashboard.html"]:
            meta_summary = _extract_meta_from_html(hp)
            if meta_summary:
                # 정상 추출 시 meta_summary.json 재건
                try:
                    clean = OUTPUT_DIR/"meta_summary.json"
                    clean.write_text(json.dumps(meta_summary, ensure_ascii=False), encoding="utf-8")
                    shutil.copy2(clean, _dir/"meta_summary.json")
                except Exception:
                    pass
                break
    if not meta_summary:
        for cp in [OUTPUT_DIR/"meta_daily_cache.json", _dir/"meta_daily_cache.json"]:
            if cp.exists():
                try:
                    meta_summary = {"daily": json.loads(cp.read_text(encoding="utf-8")), "summary": {}}
                    break
                except Exception:
                    pass

    # GA4 데이터 로드
    ga4_data = None
    for gp in [_dir/"ga4_latest.json", OUTPUT_DIR/"ga4_latest.json"]:
        if gp.exists():
            try:
                ga4_data = json.loads(gp.read_text(encoding="utf-8"))
                break
            except Exception:
                pass

    # cafe24_data.json 번들 저장 (breakdown 제외로 크기 최적화)
    meta_for_bundle = {}
    if meta_summary:
        meta_for_bundle = {
            "daily":   meta_summary.get("daily", []),
            "summary": meta_summary.get("summary", {}),
        }
    def _safe_write(src_path, dst_path):
        """shutil.copy2 대신 직접 읽고 써서 파일 잠금 문제 우회"""
        content = src_path.read_bytes()
        try:
            dst_path.write_bytes(content)
        except PermissionError:
            import time as _time
            _time.sleep(2)
            try:
                dst_path.write_bytes(content)
            except PermissionError:
                print(f"  ⚠️  {dst_path.name} 복사 실패 (파일 사용 중) — 건너뜀")

    data_bundle = {"c24": result, "meta": meta_for_bundle, "ga4": ga4_data or {}}
    data_out = OUTPUT_DIR / "cafe24_data.json"
    data_out.write_text(json.dumps(data_bundle, ensure_ascii=False, default=str), encoding="utf-8")
    _safe_write(data_out, _dir / "cafe24_data.json")
    print(f"✅ cafe24_data.json 생성 완료 ({data_out.stat().st_size:,} bytes)")

    # 대시보드 HTML 복사 (데이터 없는 fetch 템플릿 그대로)
    dash_src = _dir / "cafe24_dashboard.html"
    dash_out = OUTPUT_DIR / "cafe24_dashboard.html"
    if dash_src.exists():
        _safe_write(dash_src, dash_out)
        print(f"✅ 대시보드 HTML 복사 완료")

    if GH_TOKEN and GH_USER and GH_REPO:
        print("\nGitHub 업로드 중...")
        upload_to_github(out_path,  "cafe24_latest.json",    GH_TOKEN, GH_USER, GH_REPO, "gh-pages")
        upload_to_github(data_out,  "cafe24_data.json",      GH_TOKEN, GH_USER, GH_REPO, "gh-pages")
        if dash_out.exists():
            upload_to_github(dash_out, "cafe24_dashboard.html", GH_TOKEN, GH_USER, GH_REPO, "gh-pages")
        print(f"  → https://{GH_USER}.github.io/{GH_REPO}/cafe24_dashboard.html")

    if not _is_ci:
        input("\n[엔터] 종료")


if __name__ == "__main__":
    main()
