#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BBagio Cafe24 자사몰 데이터 수집기
- OAuth 2.0 인증 (최초 1회 수동, 이후 자동 갱신)
- 수집 항목: 매출(일별), 신규고객, 상품별 성과
- 결과: cafe24_latest.json → GitHub 업로드
"""

import os as _os
import json
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
    data = {"access_token": access, "refresh_token": refresh, "saved_at": datetime.now().isoformat()}
    with open(TOKEN_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    # config.json 업데이트 (존재할 때만)
    if cfg_path.exists():
        cfg["cafe24_access_token"] = access
        cfg["cafe24_refresh_token"] = refresh
        with open(cfg_path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=4)
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
    """최초 1회: 브라우저로 인증 후 코드 받아 토큰 교환"""
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
        print("예: https://bionex.cafe24.com/?code=XXXXX&state=...")
        redirect = input("> ").strip()
        parsed = urllib.parse.urlparse(redirect)
        params = urllib.parse.parse_qs(parsed.query)
        code = params.get("code", [None])[0]
        if not code:
            raise ValueError("URL에서 code를 찾을 수 없습니다.")
        _exchange_code(code)
    else:
        raise RuntimeError("CI 환경에서 최초 인증 불가. 로컬에서 먼저 인증 후 토큰을 GitHub Secrets에 등록하세요.")


def _exchange_code(code):
    """인증 코드 → Access Token + Refresh Token"""
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
    """Refresh Token으로 Access Token 갱신"""
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
        print(f"  토큰 갱신 실패: {e.code} — 재인증 필요")
        return None, None


def _get_valid_token():
    """유효한 Access Token 반환 (필요시 갱신/재인증)"""
    access, refresh = _load_tokens()
    if not access and not refresh:
        _do_oauth()
        return _load_tokens()[0]
    # 토큰 파일에 access_token이 있으면 먼저 refresh 시도
    if refresh:
        new_access, _ = _refresh_access_token(refresh)
        if new_access:
            return new_access
    # refresh 실패 시 현재 access_token 그대로 사용
    if access:
        print("  (refresh 실패, 기존 access_token 사용)")
        return access
    _do_oauth()
    return _load_tokens()[0]


# ──────────────────────────────────────────────
# API 호출 헬퍼
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


# ──────────────────────────────────────────────
# 데이터 수집 함수들
# ──────────────────────────────────────────────
def collect_orders_daily(token, start_date, end_date):
    """
    일별 주문/매출 수집.
    actual_order_amount.payment_amount 를 매출로 사용.
    first_order='T' 인 주문으로 신규 고객 수 산출.
    """
    print("  주문 데이터 수집 중...")
    daily = {}      # date → {orders, revenue, items, new_customers}
    page = 1

    while True:
        data = _api_get("admin/orders", token, {
            "start_date": start_date,
            "end_date":   end_date,
            "limit":      100,
            "offset":     (page - 1) * 100,
        })
        orders = data.get("orders", [])
        if not orders:
            break

        for o in orders:
            raw_date = o.get("order_date", "")
            date = raw_date[:10] if raw_date else "unknown"
            if date not in daily:
                daily[date] = {"orders": 0, "revenue": 0.0, "items": 0, "new_customers": 0, "canceled": 0}

            # 취소 여부
            if o.get("canceled") == "T":
                daily[date]["canceled"] += 1
                continue

            # 매출: actual_order_amount.payment_amount
            amt = o.get("actual_order_amount") or o.get("initial_order_amount") or {}
            revenue = float(amt.get("payment_amount", 0) or 0)

            daily[date]["orders"]  += 1
            daily[date]["revenue"] += revenue

            # 상품 수량 (items 임베드 없을 때는 0)
            for item in o.get("items", []):
                daily[date]["items"] += int(item.get("quantity", 0) or 0)

            # 신규 회원 첫 주문
            if o.get("first_order") == "T":
                daily[date]["new_customers"] += 1

        if len(orders) < 100:
            break
        page += 1

    return daily


def collect_products_performance(token, start_date, end_date):
    """
    상품/옵션별 판매 성과.
    orders embed=items 로 상품별 집계.
    """
    print("  상품별 성과 수집 중...")
    product_stats = {}
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
            if o.get("canceled") == "T":
                continue
            for item in o.get("items", []):
                pid   = str(item.get("product_no", ""))
                pname = item.get("product_name", "알 수 없음")
                # 옵션 정보: option_value 필드가 이미 문자열로 조합된 옵션명
                raw_oname = item.get("option_value", "") or ""
                if isinstance(raw_oname, (list, dict)):
                    raw_oname = str(raw_oname)
                oname = str(raw_oname).strip()

                qty   = int(item.get("quantity", 0) or 0)
                # 상품별 단가
                price_each = float(item.get("product_price", 0) or 0)
                price = price_each * qty

                if pid not in product_stats:
                    product_stats[pid] = {
                        "product_no":   pid,
                        "product_name": pname,
                        "quantity":     0,
                        "revenue":      0.0,
                        "options":      {},
                    }
                product_stats[pid]["quantity"] += qty
                product_stats[pid]["revenue"]  += price

                if oname:
                    if oname not in product_stats[pid]["options"]:
                        product_stats[pid]["options"][oname] = {
                            "option_name": oname,
                            "quantity":    0,
                            "revenue":     0.0
                        }
                    product_stats[pid]["options"][oname]["quantity"] += qty
                    product_stats[pid]["options"][oname]["revenue"]  += price

        if len(orders) < 100:
            break
        page += 1

    sorted_products = sorted(product_stats.values(), key=lambda x: x["revenue"], reverse=True)
    for p in sorted_products:
        p["options"] = sorted(p["options"].values(), key=lambda x: x["quantity"], reverse=True)
    return sorted_products


def collect_order_count(token, start_date, end_date):
    """주문 총 건수"""
    data = _api_get("admin/orders/count", token, {
        "start_date": start_date,
        "end_date":   end_date,
    })
    return data.get("count", 0) if data else 0


# ──────────────────────────────────────────────
# GitHub 업로드
# ──────────────────────────────────────────────
def upload_to_github(file_path, gh_filename, token, user, repo):
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
    get_req = urllib.request.Request(api_url, headers=headers)
    sha = None
    try:
        with urllib.request.urlopen(get_req) as r:
            sha = json.loads(r.read()).get("sha")
    except urllib.error.HTTPError:
        pass

    body = {
        "message": f"[자동] Cafe24 데이터 {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "content": content_b64,
        "branch":  "main",
    }
    if sha:
        body["sha"] = sha

    put_req = urllib.request.Request(
        api_url,
        data=json.dumps(body).encode(),
        method="PUT",
        headers=headers
    )
    try:
        with urllib.request.urlopen(put_req) as r:
            print(f"  GitHub 업로드 완료: {gh_filename}")
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
    days_back  = int(cfg.get("days_back", 30))
    start_date = (today - timedelta(days=days_back)).strftime("%Y-%m-%d")
    end_date   = today.strftime("%Y-%m-%d")
    print(f"수집 기간: {start_date} ~ {end_date} ({days_back}일)")

    result = {
        "collected_at": today.strftime("%Y-%m-%d %H:%M:%S"),
        "mall_id":      MALL_ID,
        "period":       {"start": start_date, "end": end_date, "days": days_back},
        "daily":        {},
        "products":     [],
        "summary":      {},
    }

    # 일별 주문/매출 + 신규 고객
    daily_data = collect_orders_daily(token, start_date, end_date)
    for date in sorted(daily_data.keys()):
        d = daily_data[date]
        result["daily"][date] = {
            "orders":        d["orders"],
            "revenue":       round(d["revenue"], 0),
            "items":         d["items"],
            "new_customers": d["new_customers"],
            "canceled":      d["canceled"],
        }

    # 상품별 성과
    result["products"] = collect_products_performance(token, start_date, end_date)

    # 요약 통계
    total_revenue       = sum(d["revenue"]       for d in result["daily"].values())
    total_orders        = sum(d["orders"]        for d in result["daily"].values())
    total_items         = sum(d["items"]         for d in result["daily"].values())
    total_new_customers = sum(d["new_customers"] for d in result["daily"].values())
    total_canceled      = sum(d["canceled"]      for d in result["daily"].values())

    result["summary"] = {
        "total_revenue":    round(total_revenue, 0),
        "total_orders":     total_orders,
        "total_items":      total_items,
        "avg_order_value":  round(total_revenue / total_orders, 0) if total_orders > 0 else 0,
        "new_customers":    total_new_customers,
        "canceled_orders":  total_canceled,
        "top_product":      result["products"][0]["product_name"] if result["products"] else "-",
    }

    out_path = OUTPUT_DIR / "cafe24_latest.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)

    print(f"\n✅ 수집 완료: {out_path}")
    print(f"   총 매출:  {int(total_revenue):,}원")
    print(f"   주문건:   {total_orders}건 (취소 {total_canceled}건)")
    print(f"   신규고객: {total_new_customers}명")
    if result["products"]:
        print(f"   1위 상품: {result['products'][0]['product_name'][:40]}")

    if GH_TOKEN and GH_USER and GH_REPO:
        print("\nGitHub 업로드 중...")
        upload_to_github(out_path, "cafe24_latest.json", GH_TOKEN, GH_USER, GH_REPO)

    if not _is_ci:
        input("\n[엔터] 종료")


if __name__ == "__main__":
    main()
