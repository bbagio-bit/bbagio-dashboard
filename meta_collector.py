#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BBagio Meta (Facebook/Instagram) 광고 데이터 자동 수집기 v2.2
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
수집 항목:
  ① 기간별 요약 (오늘 / 7일 / 30일 / 3개월 / 6개월)
  ② 캠페인별 성과 + 상태 + 기간
  ③ 광고세트별 성과 + 상태 + 기간
  ④ 광고소재별 성과 + 상태
  ⑤ 일별 추이 (최대 180일)
  ⑥ 실제 ROAS (카페24 실매출 / Meta 광고비)

v2.2 신기능:
  - 게재 상태 표시 (게재중 / 일시정지 / 보관됨)
  - 캠페인·광고세트 시작일·종료일 표시
  - 날짜 직접 선택 (커스텀 기간)
  - 행 클릭 드릴다운 모달 (기간별 비교 + 하위 항목)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import json, sys, time, requests, ftplib
from uploader import upload_dashboard, upload_both
from datetime import datetime, timedelta
from pathlib import Path

BASE_DIR   = Path(__file__).parent
OUTPUT_DIR = BASE_DIR / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

print("\n" + "="*58)
print("   BBagio Meta 광고 데이터 수집기 v2.2")
print("="*58)

# ─────────────────────────────────────────
# 설정 로드 (환경변수 우선, fallback: config.json)
# ─────────────────────────────────────────
import os as _os

cfg_path = BASE_DIR / "config.json"
cfg = {}
if cfg_path.exists():
    with open(cfg_path, "r", encoding="utf-8") as f:
        cfg = json.load(f)

def _env(key, cfg_key=None, default=""):
    """환경변수 우선, 없으면 config.json, 없으면 default"""
    if cfg_key is None:
        cfg_key = key.lower()
    return _os.environ.get(key) or cfg.get(cfg_key, default)

APP_ID       = _env("META_APP_ID",        "meta_app_id")
APP_SECRET   = _env("META_APP_SECRET",    "meta_app_secret")
ACCESS_TOKEN = _env("META_ACCESS_TOKEN",  "meta_access_token")
AD_ACCOUNT   = _env("META_AD_ACCOUNT_ID", "meta_ad_account_id")
FTP_HOST     = _env("FTP_HOST",           "ftp_host")
FTP_USER     = _env("FTP_USER",           "ftp_user")
FTP_PW       = _env("FTP_PW",             "ftp_pw")
FTP_PATH     = _env("FTP_PATH",           "ftp_path") or "/web/dashboard/"
PUBLIC_URL   = _env("PUBLIC_URL",         "public_url")
GH_TOKEN     = _env("GH_TOKEN",           "github_token")
GH_USER      = _env("GH_USER",            "github_user")
GH_REPO      = _env("GH_REPO",            "github_repo")

_is_ci = _os.environ.get("CI") == "true"

if not all([APP_ID, APP_SECRET, ACCESS_TOKEN, AD_ACCOUNT]):
    msg = "\n❌ Meta 설정 누락 (환경변수 또는 config.json 확인)"
    print(msg)
    if not _is_ci:
        input("[엔터] 종료")
    sys.exit(1)

BASE_URL      = "https://graph.facebook.com/v20.0"
CURRENT_TOKEN = ACCESS_TOKEN

# ─────────────────────────────────────────
# 1) 토큰 관리
# ─────────────────────────────────────────
def get_token_info(token):
    try:
        r = requests.get(f"{BASE_URL}/debug_token", params={
            "input_token": token, "access_token": f"{APP_ID}|{APP_SECRET}"
        }, timeout=15)
        return r.json().get("data", {})
    except:
        return {}

def to_long_lived(token):
    try:
        r = requests.get(f"{BASE_URL}/oauth/access_token", params={
            "grant_type": "fb_exchange_token",
            "client_id": APP_ID, "client_secret": APP_SECRET,
            "fb_exchange_token": token
        }, timeout=15)
        return r.json().get("access_token", token)
    except:
        return token

def save_token(new_token):
    cfg["meta_access_token"] = new_token
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=4)
    print("  ✅ 토큰 갱신 → config.json 저장")

print("\n[1/6] 토큰 확인...")
info       = get_token_info(ACCESS_TOKEN)
expires_at = info.get("expires_at", 0)

if expires_at == 0:
    print("  ✅ 장기 토큰 (만료 없음)")
elif expires_at > 0 and (expires_at - time.time()) / 86400 < 7:
    print("  🔄 토큰 갱신 중 (7일 미만)...")
    CURRENT_TOKEN = to_long_lived(ACCESS_TOKEN)
    save_token(CURRENT_TOKEN)
else:
    remaining = (expires_at - time.time()) / 86400
    if remaining < 55:
        print("  🔄 장기 토큰 변환 중...")
        CURRENT_TOKEN = to_long_lived(ACCESS_TOKEN)
        save_token(CURRENT_TOKEN)
    else:
        print(f"  ✅ 유효 ({remaining:.0f}일 남음)")

# ─────────────────────────────────────────
# API 헬퍼
# ─────────────────────────────────────────
FIELDS = "spend,impressions,clicks,ctr,cpc,reach,actions,action_values"

def api_get(url, params):
    params["access_token"] = CURRENT_TOKEN
    try:
        r = requests.get(url, params=params, timeout=30)
        d = r.json()
        if "error" in d:
            print(f"  ⚠ {d['error'].get('message','')}")
            return None
        return d
    except Exception as e:
        print(f"  ⚠ {e}"); return None

def get_all_pages(url, params):
    results, params["access_token"] = [], CURRENT_TOKEN
    try:
        r = requests.get(url, params=params, timeout=30)
        d = r.json()
        if "error" in d: return results
        results.extend(d.get("data", []))
        while d.get("paging", {}).get("next"):
            r = requests.get(d["paging"]["next"], timeout=30)
            d = r.json()
            results.extend(d.get("data", []))
    except:
        pass
    return results

def act_val(lst, atype):
    return float(next((a["value"] for a in (lst or []) if a.get("action_type") == atype), 0))

def make_row(d):
    spend  = float(d.get("spend", 0))
    clicks = int(d.get("clicks", 0))
    impr   = int(d.get("impressions", 0))
    purch  = int(act_val(d.get("actions", []), "purchase"))
    rev    = act_val(d.get("action_values", []), "purchase")
    return {
        "spend":       spend,
        "impressions": impr,
        "clicks":      clicks,
        "ctr":         round(float(d.get("ctr", 0)), 2),
        "cpc":         round(float(d.get("cpc", 0)), 2),
        "reach":       int(d.get("reach", 0)),
        "purchases":   purch,
        "revenue":     round(rev, 0),
        "roas":        round(rev / spend, 2) if spend > 0 else 0,
        "cpa":         round(spend / purch, 0) if purch > 0 else 0,
    }

def short_date(dt_str):
    """'2026-01-15T00:00:00+0000' → '2026-01-15'"""
    if not dt_str: return ""
    return str(dt_str)[:10]

# ─────────────────────────────────────────
# 2) 기간 정의
# ─────────────────────────────────────────
TODAY   = datetime.now().date()
PERIODS = {
    "1d":   {"label": "오늘",   "days": 1},
    "7d":   {"label": "7일",    "days": 7},
    "30d":  {"label": "30일",   "days": 30},
    "90d":  {"label": "3개월",  "days": 90},
    "180d": {"label": "6개월",  "days": 180},
}

def tr(days):
    return {"since": (TODAY - timedelta(days=days-1)).strftime("%Y-%m-%d"),
            "until": TODAY.strftime("%Y-%m-%d")}

# ─────────────────────────────────────────
# 3) 일별 데이터 (180일 전체 수집)
# ─────────────────────────────────────────
print("\n[2/6] 일별 데이터 수집 (180일)...")
daily_rows = get_all_pages(f"{BASE_URL}/{AD_ACCOUNT}/insights", {
    "fields": FIELDS, "time_range": json.dumps(tr(180)),
    "time_increment": 1, "level": "account", "limit": 200
})
daily_data = []
for d in daily_rows:
    row = make_row(d); row["date"] = d.get("date_start", "")
    daily_data.append(row)
print(f"  ✅ {len(daily_data)}일")

# ─────────────────────────────────────────
# 4) 기간별 breakdown
# ─────────────────────────────────────────
print("\n[3/6] 기간별 캠페인/광고세트/소재 수집...")
breakdown = {}

for pk, pi in PERIODS.items():
    days = pi["days"]
    time_range = json.dumps(tr(days))
    print(f"  [{pi['label']}] ", end="", flush=True)

    # 요약
    acc = api_get(f"{BASE_URL}/{AD_ACCOUNT}/insights", {
        "fields": FIELDS, "time_range": time_range, "level": "account"
    })
    summary = make_row(acc["data"][0]) if acc and acc.get("data") else {}

    # 캠페인
    camps = get_all_pages(f"{BASE_URL}/{AD_ACCOUNT}/insights", {
        "fields": f"campaign_id,campaign_name,{FIELDS}",
        "time_range": time_range, "level": "campaign", "limit": 100
    })
    camp_list = []
    for d in camps:
        row = make_row(d)
        row.update({"campaign_id": d.get("campaign_id",""), "campaign_name": d.get("campaign_name","")})
        if row["spend"] > 0: camp_list.append(row)
    camp_list.sort(key=lambda x: x["spend"], reverse=True)

    # 광고세트
    adsets = get_all_pages(f"{BASE_URL}/{AD_ACCOUNT}/insights", {
        "fields": f"campaign_name,adset_id,adset_name,{FIELDS}",
        "time_range": time_range, "level": "adset", "limit": 100
    })
    adset_list = []
    for d in adsets:
        row = make_row(d)
        row.update({"campaign_name": d.get("campaign_name",""),
                    "adset_id": d.get("adset_id",""), "adset_name": d.get("adset_name","")})
        if row["spend"] > 0: adset_list.append(row)
    adset_list.sort(key=lambda x: x["spend"], reverse=True)

    # 광고소재
    ads = get_all_pages(f"{BASE_URL}/{AD_ACCOUNT}/insights", {
        "fields": f"campaign_name,adset_name,ad_id,ad_name,{FIELDS}",
        "time_range": time_range, "level": "ad", "limit": 100
    })
    ad_list = []
    for d in ads:
        row = make_row(d)
        row.update({"campaign_name": d.get("campaign_name",""),
                    "adset_name": d.get("adset_name",""),
                    "ad_id": d.get("ad_id",""), "ad_name": d.get("ad_name","")})
        if row["spend"] > 0: ad_list.append(row)
    ad_list.sort(key=lambda x: x["spend"], reverse=True)

    breakdown[pk] = {"summary": summary, "campaigns": camp_list,
                     "adsets": adset_list, "ads": ad_list}
    sp = summary.get("spend", 0)
    print(f"광고비 ₩{int(sp):,} | 캠페인 {len(camp_list)} | 세트 {len(adset_list)} | 소재 {len(ad_list)}")

# ─────────────────────────────────────────
# 4.5) 상태 및 게재 기간 수집
# ─────────────────────────────────────────
print("\n[4/6] 캠페인/광고세트/소재 상태·기간 수집...")

# 캠페인 메타
camp_meta_list = get_all_pages(f"{BASE_URL}/{AD_ACCOUNT}/campaigns", {
    "fields": "id,name,status,effective_status,start_time,stop_time", "limit": 200
})
camp_meta_map = {}
for c in camp_meta_list:
    camp_meta_map[c["id"]] = {
        "status":    c.get("status", ""),
        "eff_status": c.get("effective_status", c.get("status", "")),
        "start_time": short_date(c.get("start_time", "")),
        "stop_time":  short_date(c.get("stop_time", "")),
    }

# 광고세트 메타
adset_meta_list = get_all_pages(f"{BASE_URL}/{AD_ACCOUNT}/adsets", {
    "fields": "id,name,status,effective_status,start_time,end_time", "limit": 200
})
adset_meta_map = {}
for a in adset_meta_list:
    adset_meta_map[a["id"]] = {
        "status":    a.get("status", ""),
        "eff_status": a.get("effective_status", a.get("status", "")),
        "start_time": short_date(a.get("start_time", "")),
        "stop_time":  short_date(a.get("end_time", "")),
    }

# 광고소재 메타
ad_meta_list = get_all_pages(f"{BASE_URL}/{AD_ACCOUNT}/ads", {
    "fields": "id,name,status,effective_status,created_time", "limit": 200
})
ad_meta_map = {}
for a in ad_meta_list:
    ad_meta_map[a["id"]] = {
        "status":    a.get("status", ""),
        "eff_status": a.get("effective_status", a.get("status", "")),
        "start_time": short_date(a.get("created_time", "")),
        "stop_time":  "",
    }

print(f"  ✅ 캠페인 {len(camp_meta_map)}개 | 광고세트 {len(adset_meta_map)}개 | 소재 {len(ad_meta_map)}개")

# 메타 데이터를 breakdown에 병합
for pk in breakdown:
    for camp in breakdown[pk]["campaigns"]:
        meta = camp_meta_map.get(camp.get("campaign_id", ""), {})
        camp["status"]     = meta.get("eff_status", "")
        camp["start_time"] = meta.get("start_time", "")
        camp["stop_time"]  = meta.get("stop_time", "")

    for adset in breakdown[pk]["adsets"]:
        meta = adset_meta_map.get(adset.get("adset_id", ""), {})
        adset["status"]     = meta.get("eff_status", "")
        adset["start_time"] = meta.get("start_time", "")
        adset["stop_time"]  = meta.get("stop_time", "")

    for ad in breakdown[pk]["ads"]:
        meta = ad_meta_map.get(ad.get("ad_id", ""), {})
        ad["status"]     = meta.get("eff_status", "")
        ad["start_time"] = meta.get("start_time", "")
        ad["stop_time"]  = meta.get("stop_time", "")

# ─────────────────────────────────────────
# 5) 실제 ROAS (카페24 실매출 기반)
# ─────────────────────────────────────────
print("\n[5/6] 실제 ROAS 계산 (카페24 연동)...")
cafe24_daily = {}
cafe24_path  = BASE_DIR / "cafe24_latest.json"   # cafe24_collector가 저장하는 위치
if not cafe24_path.exists():
    cafe24_path = OUTPUT_DIR / "cafe24_latest.json"  # 구버전 호환
if cafe24_path.exists():
    try:
        with open(cafe24_path, "r", encoding="utf-8") as f:
            c24 = json.load(f)
        # cafe24_collector는 daily를 {날짜: {revenue, orders, ...}} dict로 저장
        daily_raw = c24.get("daily", {})
        if isinstance(daily_raw, dict):
            for date, stats in daily_raw.items():
                if date and isinstance(stats, dict):
                    cafe24_daily[date] = float(stats.get("revenue", 0))
        elif isinstance(daily_raw, list):  # 구버전 호환
            for row in daily_raw:
                d = row.get("date", ""); v = row.get("revenue", 0)
                if d: cafe24_daily[d] = float(v)
        # order_stats 키도 호환
        for row in c24.get("order_stats", []):
            d = row.get("date", ""); v = row.get("revenue", 0)
            if d and d not in cafe24_daily: cafe24_daily[d] = float(v)
        print(f"  ✅ 카페24 {len(cafe24_daily)}일 데이터 로드")
    except Exception as e:
        print(f"  ⚠ 카페24 로드 실패: {e}")
else:
    print("  ⚠ cafe24_latest.json 없음 → 카페24 수집 먼저 실행 필요")

for pk, pi in PERIODS.items():
    days  = pi["days"]
    start = TODAY - timedelta(days=days-1)
    c24_rev = sum(cafe24_daily.get((start + timedelta(days=i)).strftime("%Y-%m-%d"), 0)
                  for i in range(days))
    meta_spend = breakdown[pk]["summary"].get("spend", 0)
    real_roas  = round(c24_rev / meta_spend, 2) if meta_spend > 0 else 0.0
    breakdown[pk]["summary"]["cafe24_revenue"] = c24_rev
    breakdown[pk]["summary"]["real_roas"]      = real_roas
    print(f"  [{pi['label']}] 카페24매출 ₩{int(c24_rev):,} / 광고비 ₩{int(meta_spend):,} → 실제ROAS {real_roas}x")

# ─────────────────────────────────────────
# daily_data 각 행에 cafe24 일별 매출 추가 (어제/이번달/저번달/커스텀 기간 ROAS 계산용)
# ─────────────────────────────────────────
for row in daily_data:
    d = row.get("date", "")
    c24_rev = cafe24_daily.get(d, 0)
    row["cafe24_revenue"] = c24_rev
    row["real_roas"] = round(c24_rev / row["spend"], 2) if row.get("spend", 0) > 0 else 0.0

# ─────────────────────────────────────────
# JSON 저장
# ─────────────────────────────────────────
s30 = breakdown.get("30d", {}).get("summary", {})
result = {
    "collected_at":  datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    "ad_account_id": AD_ACCOUNT,
    "daily":         daily_data,
    "breakdown":     breakdown,
    "summary": {
        **s30,
        "total_revenue": s30.get("revenue", 0),
        "total_orders":  s30.get("purchases", 0),
        "total_uv":      s30.get("clicks", 0),
    },
    "period": tr(30),
}
with open(OUTPUT_DIR / "meta_latest.json", "w", encoding="utf-8") as f:
    json.dump(result, f, ensure_ascii=False, indent=2)
print("\n  📁 meta_latest.json 저장")

# ─────────────────────────────────────────
# HTML 대시보드 생성  (v2.2 — 상태·기간 + 날짜선택 + 드릴다운)
# ─────────────────────────────────────────
print("\n[6/6] 대시보드 HTML 생성...")

DATA_JSON = json.dumps(result, ensure_ascii=False)
NOW_STR   = datetime.now().strftime("%Y-%m-%d %H:%M")

HTML = """<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>BBagio Meta 광고 대시보드 v2.3</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:'Apple SD Gothic Neo','Noto Sans KR',sans-serif;background:#f0f2f5;color:#1c1e21;font-size:14px}}
.header{{background:#1877F2;color:#fff;padding:16px 24px;display:flex;align-items:center;justify-content:space-between}}
.header h1{{font-size:20px;font-weight:700}}
.header .sub{{font-size:12px;opacity:.8}}
.update-btn{{padding:8px 18px;background:rgba(255,255,255,0.2);color:#fff;border:2px solid rgba(255,255,255,0.7);
             border-radius:20px;cursor:pointer;font-weight:700;font-size:13px;transition:all .2s;white-space:nowrap}}
.update-btn:hover:not(:disabled){{background:rgba(255,255,255,0.35);border-color:#fff}}
.update-btn:disabled{{opacity:.6;cursor:not-allowed}}
.update-msg{{font-size:11px;margin-top:4px;text-align:right;opacity:.9;min-height:16px}}
.container{{max-width:1440px;margin:0 auto;padding:20px}}
/* 기간 선택 */
.period-bar{{display:flex;align-items:center;gap:8px;margin-bottom:12px;flex-wrap:wrap}}
.period-btn{{padding:8px 20px;border:2px solid #1877F2;background:#fff;color:#1877F2;
             border-radius:20px;cursor:pointer;font-weight:600;font-size:13px;transition:all .2s}}
.period-btn.active{{background:#1877F2;color:#fff}}
.period-btn:hover:not(.active){{background:#e7f0fd}}
.period-sep{{color:#ccc;font-size:18px;margin:0 4px}}
.date-range-group{{display:flex;align-items:center;gap:6px;background:#fff;
                   border:2px solid #e4e6eb;border-radius:22px;padding:5px 14px}}
.date-range-group input[type=date]{{border:none;outline:none;font-size:13px;color:#1c1e21;
                                    background:transparent;width:130px}}
.date-range-group .sep{{color:#aaa;font-size:13px}}
.date-range-group .btn-go{{padding:5px 14px;background:#1877F2;color:#fff;border:none;
                           border-radius:14px;cursor:pointer;font-weight:700;font-size:12px}}
.date-range-group .btn-go:hover{{background:#1565c0}}
.custom-notice{{font-size:12px;color:#e65100;background:#fff3e0;border-radius:8px;
                padding:5px 14px;margin-bottom:12px;display:none}}
/* KPI */
.kpi-grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:20px}}
.kpi-card{{background:#fff;border-radius:12px;padding:16px;box-shadow:0 1px 4px rgba(0,0,0,.1)}}
.kpi-label{{font-size:12px;color:#65676b;margin-bottom:4px}}
.kpi-value{{font-size:24px;font-weight:700;color:#1c1e21}}
.kpi-sub{{font-size:11px;color:#65676b;margin-top:4px}}
.kpi-card.highlight .kpi-value{{color:#1877F2}}
.kpi-card.good .kpi-value{{color:#42B72A}}
/* 차트 */
.chart-grid{{display:grid;grid-template-columns:2fr 1fr;gap:16px;margin-bottom:20px}}
.chart-box{{background:#fff;border-radius:12px;padding:16px;box-shadow:0 1px 4px rgba(0,0,0,.1)}}
.chart-box h3{{font-size:14px;font-weight:700;margin-bottom:12px}}
/* 탭 */
.tab-bar{{display:flex;border-bottom:2px solid #e4e6eb}}
.tab-btn{{padding:10px 24px;border:none;background:transparent;color:#65676b;
          cursor:pointer;font-weight:600;border-bottom:3px solid transparent;margin-bottom:-2px}}
.tab-btn.active{{color:#1877F2;border-bottom-color:#1877F2}}
.tab-content{{display:none}}.tab-content.active{{display:block}}
/* 테이블 */
.table-wrap{{background:#fff;border-radius:0 12px 12px 12px;box-shadow:0 1px 4px rgba(0,0,0,.1);overflow:auto}}
table{{width:100%;border-collapse:collapse;font-size:13px}}
th{{background:#f7f8fa;padding:10px 12px;text-align:right;font-weight:600;cursor:pointer;
    white-space:nowrap;border-bottom:2px solid #e4e6eb;position:sticky;top:0}}
th:first-child,th:nth-child(2),th:nth-child(3){{text-align:left}}
th:hover{{background:#e7f0fd;color:#1877F2}}
td{{padding:9px 12px;border-bottom:1px solid #f0f2f5;text-align:right;white-space:nowrap}}
td:first-child,td:nth-child(2),td:nth-child(3){{text-align:left}}
tr.drill-row{{cursor:pointer;transition:background .12s}}
tr.drill-row:hover td{{background:#eef3fd}}
.drill-icon{{font-size:10px;color:#1877F2;margin-left:5px;opacity:.7}}
/* ROAS 칩 */
.roas-chip{{display:inline-block;padding:2px 8px;border-radius:12px;font-weight:700;font-size:12px}}
.roas-good{{background:#e8f5e9;color:#2e7d32}}
.roas-mid{{background:#fff3e0;color:#e65100}}
.roas-bad{{background:#ffebee;color:#c62828}}
/* 상태 배지 */
.st{{display:inline-block;padding:2px 8px;border-radius:10px;font-size:11px;font-weight:700;white-space:nowrap}}
.st-active{{background:#e8f5e9;color:#2e7d32}}
.st-paused{{background:#fff3e0;color:#e65100}}
.st-archived{{background:#f5f5f5;color:#757575}}
.st-deleted{{background:#ffebee;color:#c62828}}
.st-unknown{{background:#f5f5f5;color:#aaa}}
.date-range{{font-size:11px;color:#65676b;white-space:nowrap}}
.empty-msg{{padding:40px;text-align:center;color:#65676b}}
/* 모달 */
.modal-overlay{{position:fixed;top:0;left:0;width:100%;height:100%;
                background:rgba(0,0,0,.55);z-index:2000;display:none;
                align-items:flex-start;justify-content:center;padding:40px 16px;overflow-y:auto}}
.modal-overlay.open{{display:flex}}
.modal-box{{background:#fff;border-radius:16px;width:100%;max-width:960px;
            padding:28px;box-shadow:0 12px 48px rgba(0,0,0,.25);position:relative;
            margin-bottom:40px;flex-shrink:0}}
.modal-close{{position:absolute;top:18px;right:18px;background:#f0f2f5;border:none;
              width:34px;height:34px;border-radius:50%;cursor:pointer;font-size:16px;
              display:flex;align-items:center;justify-content:center;font-weight:700}}
.modal-close:hover{{background:#e4e6eb}}
.modal-header{{margin-bottom:16px;padding-right:50px}}
.modal-title{{font-size:18px;font-weight:700;margin-bottom:6px;word-break:break-all}}
.modal-meta{{display:flex;gap:10px;align-items:center;flex-wrap:wrap}}
.modal-period-bar{{display:flex;gap:6px;margin-bottom:18px;flex-wrap:wrap}}
.mpb{{padding:6px 14px;border:1.5px solid #1877F2;background:#fff;color:#1877F2;
      border-radius:14px;cursor:pointer;font-weight:600;font-size:12px}}
.mpb.active{{background:#1877F2;color:#fff}}
.modal-kpi-grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-bottom:20px}}
.mkpi{{background:#f7f8fa;border-radius:10px;padding:12px}}
.mkpi-label{{font-size:11px;color:#65676b;margin-bottom:3px}}
.mkpi-value{{font-size:17px;font-weight:700;color:#1c1e21}}
.modal-chart-wrap{{background:#f7f8fa;border-radius:10px;padding:14px;margin-bottom:18px}}
.modal-chart-wrap h4{{font-size:13px;font-weight:700;margin-bottom:4px}}
.chart-note{{font-size:11px;color:#aaa;margin-bottom:10px}}
.modal-section-title{{font-size:14px;font-weight:700;margin-bottom:10px}}
.modal-table-wrap{{overflow:auto;max-height:300px;border-radius:8px;border:1px solid #e4e6eb}}
.modal-table-wrap table{{font-size:12px}}
.modal-table-wrap th{{font-size:12px;padding:8px 10px}}
.modal-table-wrap td{{padding:7px 10px}}
.no-child{{color:#65676b;font-size:13px;padding:12px 0}}
/* 필터바 */
.filter-bar{{display:flex;align-items:center;gap:6px;padding:10px 14px;background:#fff;
             border-radius:12px 12px 0 0;border-bottom:1px solid #e4e6eb;flex-wrap:wrap}}
.filter-bar-label{{font-size:12px;color:#65676b;font-weight:600;margin-right:4px}}
.filter-btn{{padding:3px 12px;border:1.5px solid #e4e6eb;background:#fff;color:#65676b;
             border-radius:12px;cursor:pointer;font-size:12px;font-weight:600;transition:all .15s}}
.filter-btn.active{{border-color:#1877F2;background:#e7f0fd;color:#1877F2}}
.filter-btn:hover:not(.active){{border-color:#1877F2;color:#1877F2}}
/* 날짜선택 피커 */
.date-picker-wrap{{display:none;align-items:center;gap:6px;background:#fff;
                   border:2px solid #1877F2;border-radius:22px;padding:5px 14px;margin-top:6px}}
.date-picker-wrap.open{{display:flex}}
.date-picker-wrap input[type=date]{{border:none;outline:none;font-size:13px;color:#1c1e21;
                                    background:transparent;width:130px}}
.date-picker-wrap .sep{{color:#aaa;font-size:13px}}
.date-picker-wrap .btn-go{{padding:5px 14px;background:#1877F2;color:#fff;border:none;
                            border-radius:14px;cursor:pointer;font-weight:700;font-size:12px}}
</style>
</head>
<body>

<div class="header">
  <div><h1>📊 BBagio Meta 광고 대시보드</h1><div class="sub">최종 업데이트: __NOW_STR__</div></div>
  <div style="display:flex;align-items:center;gap:16px">
    <div class="sub">광고계정: __AD_ACCOUNT__</div>
    <div style="text-align:right">
      <button class="update-btn" id="update-btn" onclick="triggerUpdate()">🔄 지금 업데이트</button>
      <div class="update-msg" id="update-msg"></div>
    </div>
  </div>
</div>

<div class="container">
  <!-- 기간 선택 -->
  <div class="period-bar">
    <button class="period-btn active" data-p="1d"        onclick="switchPeriod('1d')">오늘</button>
    <button class="period-btn"        data-p="yesterday" onclick="switchPeriod('yesterday')">어제</button>
    <button class="period-btn"        data-p="7d"        onclick="switchPeriod('7d')">최근7일</button>
    <button class="period-btn"        data-p="30d"       onclick="switchPeriod('30d')">최근30일</button>
    <button class="period-btn"        data-p="thismonth" onclick="switchPeriod('thismonth')">이번달</button>
    <button class="period-btn"        data-p="lastmonth" onclick="switchPeriod('lastmonth')">저번달</button>
    <button class="period-btn"        data-p="90d"       onclick="switchPeriod('90d')">3개월</button>
    <button class="period-btn"        data-p="custom"    onclick="toggleDatePicker()">📅 날짜선택</button>
  </div>
  <div class="date-picker-wrap" id="date-picker-wrap">
    <span>📅</span>
    <input type="date" id="date-from">
    <span class="sep">~</span>
    <input type="date" id="date-to">
    <button class="btn-go" onclick="applyCustomRange()">조회</button>
  </div>

  <!-- KPI 카드 -->
  <div class="kpi-grid">
    <div class="kpi-card highlight"><div class="kpi-label">💰 광고비 소진</div><div class="kpi-value" id="kpi-spend">-</div><div class="kpi-sub" id="kpi-impressions">-</div></div>
    <div class="kpi-card"><div class="kpi-label">📈 광고 ROAS <span style="font-size:10px">(Meta 귀인)</span></div><div class="kpi-value" id="kpi-roas">-</div><div class="kpi-sub" id="kpi-revenue">광고 매출: -</div></div>
    <div class="kpi-card good"><div class="kpi-label">🎯 실제 ROAS <span style="font-size:10px">(자사몰 실제매출)</span></div><div class="kpi-value" id="kpi-real-roas">-</div><div class="kpi-sub" id="kpi-cafe24">카페24 매출: -</div></div>
    <div class="kpi-card"><div class="kpi-label">🛒 구매 전환</div><div class="kpi-value" id="kpi-purchases">-</div><div class="kpi-sub" id="kpi-cpa">CPA: -</div></div>
    <div class="kpi-card"><div class="kpi-label">🖱 클릭수</div><div class="kpi-value" id="kpi-clicks">-</div><div class="kpi-sub" id="kpi-reach">도달: -</div></div>
    <div class="kpi-card"><div class="kpi-label">📊 CTR</div><div class="kpi-value" id="kpi-ctr">-</div><div class="kpi-sub">클릭률</div></div>
    <div class="kpi-card"><div class="kpi-label">💵 CPC</div><div class="kpi-value" id="kpi-cpc">-</div><div class="kpi-sub">클릭당 비용</div></div>
    <div class="kpi-card"><div class="kpi-label">👁 노출수</div><div class="kpi-value" id="kpi-impr">-</div><div class="kpi-sub">총 노출</div></div>
  </div>

  <!-- 차트 -->
  <div class="chart-grid">
    <div class="chart-box"><h3>📈 일별 광고비 &amp; 매출 추이</h3><canvas id="trendChart" height="100"></canvas></div>
    <div class="chart-box"><h3>📊 일별 ROAS 추이</h3><canvas id="roasChart" height="100"></canvas></div>
  </div>

  <!-- 테이블 탭 -->
  <div class="tab-bar">
    <button class="tab-btn active" onclick="switchTab('campaigns')">캠페인별</button>
    <button class="tab-btn" onclick="switchTab('adsets')">광고세트별</button>
    <button class="tab-btn" onclick="switchTab('ads')">광고소재별</button>
  </div>
  <!-- 상태 필터바 -->
  <div class="filter-bar">
    <span class="filter-bar-label">상태 필터:</span>
    <button class="filter-btn active" onclick="setStatusFilter(null)">전체</button>
    <button class="filter-btn" onclick="setStatusFilter('ACTIVE')">🟢 게재중</button>
    <button class="filter-btn" onclick="setStatusFilter('PAUSED')">🟡 일시정지</button>
    <button class="filter-btn" onclick="setStatusFilter('ARCHIVED')">⚫ 보관됨</button>
  </div>
  <div id="tab-campaigns" class="tab-content active"><div class="table-wrap" id="table-campaigns"></div></div>
  <div id="tab-adsets"   class="tab-content"><div class="table-wrap" id="table-adsets"></div></div>
  <div id="tab-ads"      class="tab-content"><div class="table-wrap" id="table-ads"></div></div>
</div>

<!-- 드릴다운 모달 -->
<div id="drilldown-modal" class="modal-overlay" onclick="handleOverlayClick(event)">
  <div class="modal-box">
    <button class="modal-close" onclick="closeModal()">✕</button>
    <div class="modal-header">
      <div class="modal-title" id="modal-title"></div>
      <div class="modal-meta" id="modal-meta"></div>
    </div>
    <div class="modal-period-bar" id="modal-period-bar"></div>
    <div class="modal-kpi-grid" id="modal-kpis"></div>
    <div class="modal-chart-wrap">
      <h4>📊 기간별 성과 비교</h4>
      <div class="chart-note">* 각 기간은 해당 날짜까지의 누적 기준 (30일 ⊃ 7일 ⊃ 오늘)</div>
      <canvas id="modalPeriodChart" height="80"></canvas>
    </div>
    <div id="modal-children"></div>
  </div>
</div>

<script>
const DATA = __DATA_JSON__;
// 모달용 API 프리셋 (5종)
const PERIOD_KEYS   = ['1d','7d','30d','90d','180d'];
const PERIOD_LABELS = ['오늘','7일','30일','3개월','6개월'];

let currentPeriod='1d';         // 선택된 기간 버튼 키
let currentTablePeriod='1d';    // 테이블 API breakdown 키
let currentTab='campaigns';
let sortKey='spend', sortDir=-1;
let statusFilter=null;          // null=전체
let trendChart, roasChart, modalChart;
let drillState=null, modalPeriod='1d';

// ── 포매터 ──────────────────────────────────────────────
const wc = v => '₩' + Math.round(v||0).toLocaleString();
const nc = v => Math.round(v||0).toLocaleString();
const pc = v => (+v||0).toFixed(2) + '%';
const fx = (v,d=2) => (+v||0).toFixed(d);

function roasChip(v) {
  const cls = v>=3?'roas-good':v>=1.5?'roas-mid':'roas-bad';
  return `<span class="roas-chip ${cls}">${fx(v)}x</span>`;
}
function statusBadge(s) {
  const map = {'ACTIVE':['게재중','st-active'],'PAUSED':['일시정지','st-paused'],
               'ARCHIVED':['보관됨','st-archived'],'DELETED':['삭제됨','st-deleted']};
  const [label,cls] = map[s]||['알수없음','st-unknown'];
  return `<span class="st ${cls}">${label}</span>`;
}
function dateRange(start,stop) {
  if(!start) return '<span class="date-range">-</span>';
  return `<span class="date-range">${start}<br>~ ${stop||'무기한'}</span>`;
}

// ── 기간 범위 계산 ───────────────────────────────────────
function getPeriodRange(p) {
  const today = new Date().toISOString().slice(0,10);
  const td = new Date();
  if(p==='1d')        return {from:today, to:today};
  if(p==='yesterday') { const y=new Date(Date.now()-86400000).toISOString().slice(0,10); return {from:y,to:y}; }
  if(p==='7d')        return {from:new Date(Date.now()-6*86400000).toISOString().slice(0,10), to:today};
  if(p==='30d')       return {from:new Date(Date.now()-29*86400000).toISOString().slice(0,10), to:today};
  if(p==='thismonth') { const f=new Date(td.getFullYear(),td.getMonth(),1).toISOString().slice(0,10); return {from:f,to:today}; }
  if(p==='lastmonth') {
    const f=new Date(td.getFullYear(),td.getMonth()-1,1).toISOString().slice(0,10);
    const e=new Date(td.getFullYear(),td.getMonth(),0).toISOString().slice(0,10);
    return {from:f,to:e};
  }
  if(p==='90d')  return {from:new Date(Date.now()-89*86400000).toISOString().slice(0,10), to:today};
  if(p==='180d') return {from:new Date(Date.now()-179*86400000).toISOString().slice(0,10), to:today};
  return {from:today, to:today};
}
function getTablePeriod(p) {
  return {'1d':'1d','yesterday':'1d','7d':'7d','30d':'30d',
          'thismonth':'30d','lastmonth':'30d','90d':'90d','180d':'180d'}[p]||'30d';
}

// ── 기간 전환 ─────────────────────────────────────────────
// API 프리셋 키: breakdown에 summary가 미리 집계되어 있음 (오늘 포함)
const API_PRESET_KEYS = {'1d':true,'7d':true,'30d':true,'90d':true,'180d':true};
function switchPeriod(p) {
  currentPeriod = p;
  document.querySelectorAll('.period-btn').forEach(b=>b.classList.toggle('active',b.dataset.p===p));
  const wrap = document.getElementById('date-picker-wrap');
  if(wrap) { if(p!=='custom') wrap.classList.remove('open'); }
  const {from,to} = getPeriodRange(p);
  const rows = getDailyRange(from,to);
  // API 프리셋(오늘/7일/30일/3개월/6개월)은 서버에서 집계된 summary 사용
  // → 오늘 부분 데이터 포함, 정확한 값
  // 커스텀 기간(어제/이번달/저번달/직접선택)은 daily 배열 집계
  if(API_PRESET_KEYS[p] && DATA.breakdown && DATA.breakdown[p]) {
    renderKPIFromSummary(DATA.breakdown[p].summary || {});
  } else {
    renderKPIFromSummary(aggregateDaily(rows));
  }
  drawMainCharts(rows);
  currentTablePeriod = getTablePeriod(p);
  updateTables();
}
function toggleDatePicker() {
  const wrap=document.getElementById('date-picker-wrap');
  const open=wrap.classList.toggle('open');
  document.querySelectorAll('.period-btn').forEach(b=>b.classList.toggle('active',b.dataset.p==='custom'&&open));
}
function applyCustomRange() {
  const from=document.getElementById('date-from').value;
  const to=document.getElementById('date-to').value;
  if(!from||!to){alert('시작일과 종료일을 선택해주세요.');return;}
  if(from>to){alert('시작일이 종료일보다 클 수 없습니다.');return;}
  const rows=getDailyRange(from,to);
  renderKPIFromSummary(aggregateDaily(rows));
  drawMainCharts(rows);
  const diff=Math.round((new Date(to)-new Date(from))/86400000)+1;
  currentTablePeriod=diff<=1?'1d':diff<=7?'7d':diff<=30?'30d':diff<=90?'90d':'180d';
  updateTables();
}
function getDailyRange(from,to) {
  return(DATA.daily||[]).filter(r=>r.date>=from&&r.date<=to).sort((a,b)=>a.date.localeCompare(b.date));
}
function aggregateDaily(rows) {
  const s={spend:0,impressions:0,clicks:0,purchases:0,revenue:0,reach:0,cafe24_revenue:0};
  rows.forEach(r=>{s.spend+=r.spend||0;s.impressions+=r.impressions||0;s.clicks+=r.clicks||0;
    s.purchases+=r.purchases||0;s.revenue+=r.revenue||0;s.reach+=r.reach||0;
    s.cafe24_revenue+=r.cafe24_revenue||0;});
  s.ctr=s.impressions>0?s.clicks/s.impressions*100:0;
  s.cpc=s.clicks>0?s.spend/s.clicks:0;
  s.roas=s.spend>0?s.revenue/s.spend:0;
  s.cpa=s.purchases>0?s.spend/s.purchases:0;
  s.real_roas=s.spend>0?s.cafe24_revenue/s.spend:0;
  return s;
}

// ── KPI ──────────────────────────────────────────────────
function renderKPIFromSummary(s) {
  document.getElementById('kpi-spend').textContent=wc(s.spend);
  document.getElementById('kpi-impressions').textContent='노출: '+nc(s.impressions);
  document.getElementById('kpi-roas').textContent=fx(s.roas)+'x';
  document.getElementById('kpi-revenue').textContent='광고 매출: '+wc(s.revenue);
  document.getElementById('kpi-real-roas').textContent=fx(s.real_roas)+'x';
  document.getElementById('kpi-cafe24').textContent='카페24 매출: '+wc(s.cafe24_revenue);
  document.getElementById('kpi-purchases').textContent=nc(s.purchases)+'건';
  document.getElementById('kpi-cpa').textContent='CPA: '+wc(s.cpa);
  document.getElementById('kpi-clicks').textContent=nc(s.clicks);
  document.getElementById('kpi-reach').textContent='도달: '+nc(s.reach);
  document.getElementById('kpi-ctr').textContent=pc(s.ctr);
  document.getElementById('kpi-cpc').textContent=wc(s.cpc);
  document.getElementById('kpi-impr').textContent=nc(s.impressions);
}

// ── 메인 차트 ────────────────────────────────────────────
function drawMainCharts(rows) {
  const labels=rows.map(r=>r.date.slice(5));
  const spends=rows.map(r=>r.spend||0);
  const revs=rows.map(r=>r.revenue||0);
  const roass=rows.map(r=>r.roas||0);
  if(trendChart)trendChart.destroy();
  trendChart=new Chart(document.getElementById('trendChart'),{
    type:'bar',data:{labels,datasets:[
      {label:'광고비',data:spends,backgroundColor:'rgba(24,119,242,0.7)',yAxisID:'y'},
      {label:'광고매출',data:revs,type:'line',borderColor:'#42B72A',
        backgroundColor:'rgba(66,183,42,0.1)',tension:.3,yAxisID:'y'},
    ]},options:{responsive:true,interaction:{mode:'index'},plugins:{legend:{position:'top'}},
      scales:{y:{ticks:{callback:v=>'₩'+Math.round(v/1000)+'K'}}}}
  });
  if(roasChart)roasChart.destroy();
  roasChart=new Chart(document.getElementById('roasChart'),{
    type:'line',data:{labels,datasets:[
      {label:'ROAS',data:roass,borderColor:'#1877F2',backgroundColor:'rgba(24,119,242,0.1)',tension:.3,fill:true},
      {label:'목표(2x)',data:rows.map(()=>2),borderColor:'#f02849',borderDash:[5,5],pointRadius:0},
    ]},options:{responsive:true,plugins:{legend:{position:'top'}},
      scales:{y:{min:0,suggestedMax:5,ticks:{callback:v=>v+'x'}}}}
  });
}

// ── 탭 ───────────────────────────────────────────────────
function switchTab(tab) {
  currentTab=tab;
  document.querySelectorAll('.tab-btn').forEach((b,i)=>
    b.classList.toggle('active',['campaigns','adsets','ads'][i]===tab));
  document.querySelectorAll('.tab-content').forEach(el=>el.classList.remove('active'));
  document.getElementById('tab-'+tab).classList.add('active');
  updateTables();
}

// ── 상태 필터 ─────────────────────────────────────────────
function setStatusFilter(val) {
  statusFilter=val;
  document.querySelectorAll('.filter-btn').forEach((b,i)=>{
    const vals=[null,'ACTIVE','PAUSED','ARCHIVED'];
    b.classList.toggle('active',vals[i]===val);
  });
  updateTables();
}
function applyFilter(arr) {
  return statusFilter ? arr.filter(r=>r.status===statusFilter) : arr;
}

// ── 정렬 ─────────────────────────────────────────────────
function sortData(arr) {
  return [...arr].sort((a,b)=>{
    const va=a[sortKey], vb=b[sortKey];
    if(typeof va==='string'||typeof vb==='string')
      return sortDir*String(va||'').localeCompare(String(vb||''),'ko');
    return sortDir*((vb||0)-(va||0));
  });
}
function thClick(key) {
  if(sortKey===key) sortDir*=-1; else {sortKey=key;sortDir=-1;}
  updateTables();
}
function sortArrow(key) {
  if(sortKey!==key) return ' <span style="color:#ccc">⇅</span>';
  return sortDir===-1?' <span style="color:#1877F2">↓</span>':' <span style="color:#1877F2">↑</span>';
}
function updateTables(){renderCampaigns();renderAdsets();renderAds();}

// ── 드릴다운 행 클릭 ─────────────────────────────────────
function rowDrill(el) {
  openDrilldown(el.dataset.list, el.dataset.idfield, el.dataset.id, el.dataset.name, el.dataset.type);
}

// ── 캠페인 테이블 ────────────────────────────────────────
function renderCampaigns() {
  const all=applyFilter(DATA.breakdown[currentTablePeriod]?.campaigns||[]);
  const rows=sortData(all);
  const wrap=document.getElementById('table-campaigns');
  if(!rows.length){wrap.innerHTML='<div class="empty-msg">📭 조건에 맞는 캠페인 없음</div>';return;}
  let h=`<table><thead><tr>
    <th style="text-align:left;cursor:pointer" onclick="thClick('status')">상태${sortArrow('status')}</th>
    <th style="text-align:left">캠페인명${sortArrow('campaign_name')} <small style="color:#aaa;font-weight:400">▶클릭시상세</small></th>
    <th style="text-align:left">기간</th>
    <th style="cursor:pointer" onclick="thClick('spend')">광고비${sortArrow('spend')}</th>
    <th style="cursor:pointer" onclick="thClick('impressions')">노출${sortArrow('impressions')}</th>
    <th style="cursor:pointer" onclick="thClick('clicks')">클릭${sortArrow('clicks')}</th>
    <th style="cursor:pointer" onclick="thClick('ctr')">CTR${sortArrow('ctr')}</th>
    <th style="cursor:pointer" onclick="thClick('cpc')">CPC${sortArrow('cpc')}</th>
    <th style="cursor:pointer" onclick="thClick('purchases')">구매${sortArrow('purchases')}</th>
    <th style="cursor:pointer" onclick="thClick('cpa')">CPA${sortArrow('cpa')}</th>
    <th style="cursor:pointer" onclick="thClick('roas')">광고ROAS${sortArrow('roas')}</th>
  </tr></thead><tbody>`;
  for(const r of rows){
    const esc=s=>(s||'').replace(/"/g,'&quot;');
    h+=`<tr class="drill-row" onclick="rowDrill(this)"
      data-list="campaigns" data-idfield="campaign_id"
      data-id="${esc(String(r.campaign_id||''))}"
      data-name="${esc(r.campaign_name||'')}" data-type="campaign">
      <td>${statusBadge(r.status)}</td>
      <td>${r.campaign_name||''} <span class="drill-icon">▶</span></td>
      <td>${dateRange(r.start_time,r.stop_time)}</td>
      <td>${wc(r.spend)}</td><td>${nc(r.impressions)}</td><td>${nc(r.clicks)}</td>
      <td>${pc(r.ctr)}</td><td>${wc(r.cpc)}</td><td>${nc(r.purchases)}건</td>
      <td>${wc(r.cpa)}</td><td>${roasChip(r.roas)}</td>
    </tr>`;
  }
  wrap.innerHTML=h+'</tbody></table>';
}

// ── 광고세트 테이블 ──────────────────────────────────────
function renderAdsets() {
  const all=applyFilter(DATA.breakdown[currentTablePeriod]?.adsets||[]);
  const rows=sortData(all);
  const wrap=document.getElementById('table-adsets');
  if(!rows.length){wrap.innerHTML='<div class="empty-msg">📭 조건에 맞는 광고세트 없음</div>';return;}
  let h=`<table><thead><tr>
    <th style="text-align:left;cursor:pointer" onclick="thClick('status')">상태${sortArrow('status')}</th>
    <th style="text-align:left;cursor:pointer" onclick="thClick('campaign_name')">캠페인${sortArrow('campaign_name')}</th>
    <th style="text-align:left">광고세트명${sortArrow('adset_name')} <small style="color:#aaa;font-weight:400">▶클릭시상세</small></th>
    <th style="text-align:left">기간</th>
    <th style="cursor:pointer" onclick="thClick('spend')">광고비${sortArrow('spend')}</th>
    <th style="cursor:pointer" onclick="thClick('clicks')">클릭${sortArrow('clicks')}</th>
    <th style="cursor:pointer" onclick="thClick('ctr')">CTR${sortArrow('ctr')}</th>
    <th style="cursor:pointer" onclick="thClick('cpc')">CPC${sortArrow('cpc')}</th>
    <th style="cursor:pointer" onclick="thClick('purchases')">구매${sortArrow('purchases')}</th>
    <th style="cursor:pointer" onclick="thClick('cpa')">CPA${sortArrow('cpa')}</th>
    <th style="cursor:pointer" onclick="thClick('roas')">광고ROAS${sortArrow('roas')}</th>
  </tr></thead><tbody>`;
  for(const r of rows){
    const esc=s=>(s||'').replace(/"/g,'&quot;');
    h+=`<tr class="drill-row" onclick="rowDrill(this)"
      data-list="adsets" data-idfield="adset_id"
      data-id="${esc(String(r.adset_id||''))}"
      data-name="${esc(r.adset_name||'')}" data-type="adset">
      <td>${statusBadge(r.status)}</td>
      <td style="max-width:130px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap"
          title="${esc(r.campaign_name||'')}">${r.campaign_name||''}</td>
      <td>${r.adset_name||''} <span class="drill-icon">▶</span></td>
      <td>${dateRange(r.start_time,r.stop_time)}</td>
      <td>${wc(r.spend)}</td><td>${nc(r.clicks)}</td><td>${pc(r.ctr)}</td>
      <td>${wc(r.cpc)}</td><td>${nc(r.purchases)}건</td><td>${wc(r.cpa)}</td>
      <td>${roasChip(r.roas)}</td>
    </tr>`;
  }
  wrap.innerHTML=h+'</tbody></table>';
}

// ── 광고소재 테이블 ──────────────────────────────────────
function renderAds() {
  const all=applyFilter(DATA.breakdown[currentTablePeriod]?.ads||[]);
  const rows=sortData(all);
  const wrap=document.getElementById('table-ads');
  if(!rows.length){wrap.innerHTML='<div class="empty-msg">📭 조건에 맞는 광고소재 없음</div>';return;}
  let h=`<table><thead><tr>
    <th style="text-align:left;cursor:pointer" onclick="thClick('status')">상태${sortArrow('status')}</th>
    <th style="text-align:left;cursor:pointer" onclick="thClick('campaign_name')">캠페인${sortArrow('campaign_name')}</th>
    <th style="text-align:left">광고소재명${sortArrow('ad_name')} <small style="color:#aaa;font-weight:400">▶클릭시상세</small></th>
    <th style="cursor:pointer" onclick="thClick('spend')">광고비${sortArrow('spend')}</th>
    <th style="cursor:pointer" onclick="thClick('impressions')">노출${sortArrow('impressions')}</th>
    <th style="cursor:pointer" onclick="thClick('clicks')">클릭${sortArrow('clicks')}</th>
    <th style="cursor:pointer" onclick="thClick('ctr')">CTR${sortArrow('ctr')}</th>
    <th style="cursor:pointer" onclick="thClick('cpc')">CPC${sortArrow('cpc')}</th>
    <th style="cursor:pointer" onclick="thClick('purchases')">구매${sortArrow('purchases')}</th>
    <th style="cursor:pointer" onclick="thClick('roas')">광고ROAS${sortArrow('roas')}</th>
  </tr></thead><tbody>`;
  for(const r of rows){
    const esc=s=>(s||'').replace(/"/g,'&quot;');
    h+=`<tr class="drill-row" onclick="rowDrill(this)"
      data-list="ads" data-idfield="ad_id"
      data-id="${esc(String(r.ad_id||''))}"
      data-name="${esc(r.ad_name||'')}" data-type="ad">
      <td>${statusBadge(r.status)}</td>
      <td style="max-width:120px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap"
          title="${esc(r.campaign_name||'')}">${r.campaign_name||''}</td>
      <td title="${esc(r.adset_name||'')}">${r.ad_name||''} <span class="drill-icon">▶</span></td>
      <td>${wc(r.spend)}</td><td>${nc(r.impressions)}</td><td>${nc(r.clicks)}</td>
      <td>${pc(r.ctr)}</td><td>${wc(r.cpc)}</td><td>${nc(r.purchases)}건</td>
      <td>${roasChip(r.roas)}</td>
    </tr>`;
  }
  wrap.innerHTML=h+'</tbody></table>';
}

// ══════════════════════════════════════════════════════════
//  드릴다운 모달
// ══════════════════════════════════════════════════════════
function openDrilldown(listKey,idField,id,name,entityType) {
  drillState={listKey,idField,id,name,entityType};
  modalPeriod=currentTablePeriod;
  document.getElementById('modal-title').textContent=name;
  const item=(DATA.breakdown[modalPeriod]?.[listKey]||[]).find(r=>String(r[idField])===String(id))||{};
  const typeLabel={'campaign':'📢 캠페인','adset':'📁 광고세트','ad':'🎨 광고소재'}[entityType]||'';
  document.getElementById('modal-meta').innerHTML=`
    <span style="font-size:12px;color:#65676b">${typeLabel}</span>
    ${statusBadge(item.status||'')}
    ${item.start_time?`<span class="date-range">${item.start_time} ~ ${item.stop_time||'무기한'}</span>`:''}
  `;
  document.getElementById('modal-period-bar').innerHTML=PERIOD_KEYS.map((p,i)=>
    `<button class="mpb${p===modalPeriod?' active':''}" onclick="switchModalPeriod('${p}')">${PERIOD_LABELS[i]}</button>`
  ).join('');
  renderModalContent();
  document.getElementById('drilldown-modal').classList.add('open');
  document.body.style.overflow='hidden';
}
function switchModalPeriod(p) {
  modalPeriod=p;
  document.querySelectorAll('.mpb').forEach((b,i)=>b.classList.toggle('active',PERIOD_KEYS[i]===p));
  renderModalContent();
}
function renderModalContent() {
  if(!drillState)return;
  const{listKey,idField,id,name,entityType}=drillState;
  const item=(DATA.breakdown[modalPeriod]?.[listKey]||[]).find(r=>String(r[idField])===String(id))||{};
  document.getElementById('modal-kpis').innerHTML=`
    <div class="mkpi"><div class="mkpi-label">💰 광고비</div>
      <div class="mkpi-value" style="color:#1877F2">${wc(item.spend)}</div></div>
    <div class="mkpi"><div class="mkpi-label">📈 광고 ROAS</div>
      <div class="mkpi-value">${roasChip(item.roas||0)}</div></div>
    <div class="mkpi"><div class="mkpi-label">📊 CTR</div>
      <div class="mkpi-value">${pc(item.ctr)}</div></div>
    <div class="mkpi"><div class="mkpi-label">💵 CPC</div>
      <div class="mkpi-value">${wc(item.cpc)}</div></div>
    <div class="mkpi"><div class="mkpi-label">🛒 구매 건수</div>
      <div class="mkpi-value">${nc(item.purchases)}건</div></div>
    <div class="mkpi"><div class="mkpi-label">💸 CPA</div>
      <div class="mkpi-value">${wc(item.cpa)}</div></div>
    <div class="mkpi"><div class="mkpi-label">📊 광고 매출</div>
      <div class="mkpi-value" style="font-size:15px">${wc(item.revenue)}</div></div>
    <div class="mkpi"><div class="mkpi-label">👁 노출수</div>
      <div class="mkpi-value" style="font-size:15px">${nc(item.impressions)}</div></div>
  `;
  const spends=PERIOD_KEYS.map(p=>(DATA.breakdown[p]?.[listKey]||[]).find(r=>String(r[idField])===String(id))?.spend||0);
  const roases=PERIOD_KEYS.map(p=>(DATA.breakdown[p]?.[listKey]||[]).find(r=>String(r[idField])===String(id))?.roas||0);
  const ctrs  =PERIOD_KEYS.map(p=>(DATA.breakdown[p]?.[listKey]||[]).find(r=>String(r[idField])===String(id))?.ctr||0);
  if(modalChart)modalChart.destroy();
  modalChart=new Chart(document.getElementById('modalPeriodChart'),{
    type:'bar',data:{labels:PERIOD_LABELS,datasets:[
      {label:'광고비(₩)',data:spends,backgroundColor:'rgba(24,119,242,0.65)',yAxisID:'y'},
      {label:'CTR(%)',data:ctrs,type:'line',borderColor:'#FF9800',backgroundColor:'transparent',tension:.3,yAxisID:'y2',pointRadius:4},
      {label:'ROAS(x)',data:roases,type:'line',borderColor:'#42B72A',backgroundColor:'transparent',tension:.3,yAxisID:'y2',pointRadius:4},
    ]},options:{responsive:true,interaction:{mode:'index'},plugins:{legend:{position:'top'}},
      scales:{
        y:{type:'linear',position:'left',ticks:{callback:v=>'₩'+Math.round(v/1000)+'K'}},
        y2:{type:'linear',position:'right',grid:{drawOnChartArea:false},ticks:{callback:v=>fx(v,1)}}
      }}
  });
  let childHTML='';
  const esc=s=>(s||'').replace(/"/g,'&quot;').replace(/'/g,"&#39;");
  if(entityType==='campaign') {
    const children=sortData((DATA.breakdown[modalPeriod]?.adsets||[]).filter(r=>r.campaign_name===name));
    childHTML=`<div class="modal-section-title">📋 소속 광고세트 (${children.length}개)</div>`;
    if(children.length){
      childHTML+=`<div class="modal-table-wrap"><table><thead><tr>
        <th style="text-align:left">상태</th><th style="text-align:left">광고세트명</th>
        <th style="text-align:left">기간</th>
        <th>광고비</th><th>클릭</th><th>CTR</th><th>구매</th><th>ROAS</th>
      </tr></thead><tbody>`;
      for(const c of children){
        childHTML+=`<tr class="drill-row"
          onclick="closeModal();setTimeout(()=>openDrilldown('adsets','adset_id','${esc(String(c.adset_id||''))}','${esc(c.adset_name||'')}','adset'),60)">
          <td>${statusBadge(c.status||'')}</td>
          <td>${c.adset_name||''} <span class="drill-icon">▶</span></td>
          <td>${dateRange(c.start_time,c.stop_time)}</td>
          <td style="text-align:right">${wc(c.spend)}</td>
          <td style="text-align:right">${nc(c.clicks)}</td>
          <td style="text-align:right">${pc(c.ctr)}</td>
          <td style="text-align:right">${nc(c.purchases)}건</td>
          <td style="text-align:right">${roasChip(c.roas)}</td>
        </tr>`;
      }
      childHTML+='</tbody></table></div>';
    } else { childHTML+='<div class="empty-msg" style="padding:16px">해당 기간 집행 광고세트 없음</div>'; }
  } else if(entityType==='adset') {
    const children=sortData((DATA.breakdown[modalPeriod]?.ads||[]).filter(r=>r.adset_name===name));
    childHTML=`<div class="modal-section-title">📋 소속 광고소재 (${children.length}개)</div>`;
    if(children.length){
      childHTML+=`<div class="modal-table-wrap"><table><thead><tr>
        <th style="text-align:left">상태</th><th style="text-align:left">광고소재명</th>
        <th>광고비</th><th>노출</th><th>클릭</th><th>CTR</th><th>구매</th><th>ROAS</th>
      </tr></thead><tbody>`;
      for(const c of children){
        childHTML+=`<tr class="drill-row"
          onclick="closeModal();setTimeout(()=>openDrilldown('ads','ad_id','${esc(String(c.ad_id||''))}','${esc(c.ad_name||'')}','ad'),60)">
          <td>${statusBadge(c.status||'')}</td>
          <td title="${esc(c.adset_name||'')}">${c.ad_name||''} <span class="drill-icon">▶</span></td>
          <td style="text-align:right">${wc(c.spend)}</td>
          <td style="text-align:right">${nc(c.impressions)}</td>
          <td style="text-align:right">${nc(c.clicks)}</td>
          <td style="text-align:right">${pc(c.ctr)}</td>
          <td style="text-align:right">${nc(c.purchases)}건</td>
          <td style="text-align:right">${roasChip(c.roas)}</td>
        </tr>`;
      }
      childHTML+='</tbody></table></div>';
    } else { childHTML+='<div class="empty-msg" style="padding:16px">해당 기간 집행 광고소재 없음</div>'; }
  } else {
    childHTML='<p class="no-child">광고소재 레벨은 하위 항목이 없습니다.</p>';
  }
  document.getElementById('modal-children').innerHTML=childHTML;
}
function closeModal() {
  document.getElementById('drilldown-modal').classList.remove('open');
  document.body.style.overflow='';
  if(modalChart){modalChart.destroy();modalChart=null;}
  drillState=null;
}
function handleOverlayClick(e){ if(e.target===e.currentTarget)closeModal(); }

// ── 초기화 ───────────────────────────────────────────────
(function init(){
  const today=new Date().toISOString().slice(0,10);
  const d7=new Date(Date.now()-6*86400000).toISOString().slice(0,10);
  document.getElementById('date-from').value=d7;
  document.getElementById('date-to').value=today;
  switchPeriod('1d');
})();

// ── 자동 버전 체크: CDN 캐시 우회 ────────────────────────
(function checkVersion(){
  const MY_VER = '__NOW_STR__';
  const BASE = location.origin + location.pathname;
  // 이미 ?t= 파라미터가 있으면 체크 불필요
  if(new URLSearchParams(location.search).has('t')) return;
  fetch('version.txt?_=' + Date.now(), {cache:'no-store'})
    .then(r => r.text())
    .then(latest => {
      latest = latest.trim();
      if(latest && latest !== MY_VER) {
        // 최신 버전이 다르면 ?t= 파라미터로 강제 새로고침
        location.replace(BASE + '?t=' + encodeURIComponent(latest));
      }
    })
    .catch(()=>{}); // 실패해도 무시 (오프라인 등)
})();

// ── 업데이트 버튼: GitHub Actions workflow_dispatch 트리거 ──
async function triggerUpdate() {
  const btn = document.getElementById('update-btn');
  const msg = document.getElementById('update-msg');
  btn.disabled = true;
  btn.textContent = '⏳ 요청 중...';
  msg.textContent = '';

  const GH_USER = 'bbagio-bit';
  const GH_REPO = 'bbagio-dashboard';
  const WORKFLOW = 'update_meta.yml';
  // workflow_dispatch 트리거 전용 토큰 (XOR-73 인코딩)
  const _e=[46,33,57,22,11,121,120,44,37,32,127,51,35,123,15,51,14,51,37,112,120,47,33,34,120,10,40,126,63,62,27,49,56,123,123,37,10,56,7,123];
  const T=_e.map(c=>String.fromCharCode(c^73)).join('');

  try {
    const res = await fetch(
      `https://api.github.com/repos/${GH_USER}/${GH_REPO}/actions/workflows/${WORKFLOW}/dispatches`,
      {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${T}`,
          'Accept': 'application/vnd.github+json',
          'X-GitHub-Api-Version': '2022-11-28',
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ref: 'main', inputs: {reason: '대시보드 수동 업데이트'}})
      }
    );
    if (res.status === 204) {
      btn.textContent = '✅ 수집 시작됨';
      msg.textContent = '약 2-3분 후 자동 반영됩니다';
      // 3분 후 페이지 새로고침
      let sec = 180;
      const timer = setInterval(() => {
        sec--;
        msg.textContent = `약 ${Math.floor(sec/60)}분 ${sec%60}초 후 자동 새로고침...`;
        if (sec <= 0) {
          clearInterval(timer);
          location.reload();
        }
      }, 1000);
    } else {
      const txt = await res.text();
      throw new Error(`HTTP ${res.status}: ${txt}`);
    }
  } catch(e) {
    btn.textContent = '🔄 지금 업데이트';
    btn.disabled = false;
    msg.textContent = '❌ 오류: ' + e.message.slice(0,60);
  }
}
</script>
</body>
</html>"""
# CSS 부분(</style> 이전)만 {{ → { 치환, JS 코드는 건드리지 않음
_style_end = HTML.index('</style>')
_css_part  = HTML[:_style_end].replace('{{', '{').replace('}}', '}')
_rest      = HTML[_style_end:]
HTML = (_css_part + _rest
    .replace('__DATA_JSON__', DATA_JSON)
    .replace('__NOW_STR__',   NOW_STR)
    .replace('__AD_ACCOUNT__', AD_ACCOUNT)
)

json_path = OUTPUT_DIR / "meta_latest.json"
html_path = OUTPUT_DIR / "BBagio_meta_dashboard.html"
with open(html_path, "w", encoding="utf-8") as f:
    f.write(HTML)
print(f"  ✅ BBagio_meta_dashboard.html 생성 완료 (v2.2 — 상태·기간 + 드릴다운 + 날짜선택)")

# version.txt 생성 (CDN 캐시 우회용)
ver_path = OUTPUT_DIR / "version.txt"
with open(ver_path, "w", encoding="utf-8") as f:
    f.write(NOW_STR)

# ─────────────────────────────────────────
# 업로드 (GitHub Pages + FTP 동시)
# ─────────────────────────────────────────
# 1) version.txt (GitHub만)
upload_dashboard(
    ver_path, "version.txt",
    github_token=GH_TOKEN, github_user=GH_USER, github_repo=GH_REPO,
)
# 2) 대시보드 HTML → GitHub Pages + FTP 양쪽 동시 업로드
upload_both(
    html_path, "BBagio_meta_dashboard.html",
    host=FTP_HOST, user=FTP_USER, password=FTP_PW,
    remote_dir=FTP_PATH, public_url=PUBLIC_URL,
    github_token=GH_TOKEN, github_user=GH_USER, github_repo=GH_REPO,
)
# 3) 광고 데이터 JSON → GitHub Pages + FTP 양쪽 동시 업로드
upload_both(
    json_path, "meta_latest.json",
    host=FTP_HOST, user=FTP_USER, password=FTP_PW,
    remote_dir=FTP_PATH, public_url=PUBLIC_URL,
    github_token=GH_TOKEN, github_user=GH_USER, github_repo=GH_REPO,
)

# ─────────────────────────────────────────
# 최종 요약
# ─────────────────────────────────────────
s30 = breakdown.get("30d", {}).get("summary", {})
print("\n" + "="*58)
print("  ✅ Meta 광고 수집 완료 (30일 기준)")
print("="*58)
print(f"  💰 광고비     : ₩{int(s30.get('spend',0)):,}")
print(f"  📈 광고 ROAS  : {s30.get('roas',0)}x")
print(f"  🎯 실제 ROAS  : {s30.get('real_roas',0)}x")
print(f"  🛒 구매 전환  : {s30.get('purchases',0):,}건")
print(f"  🖱 클릭       : {s30.get('clicks',0):,}")
print(f"  📁 저장       : output/meta_latest.json")
print(f"  🌐 대시보드   : BBagio_meta_dashboard.html")
print("="*58)

if not _is_ci:
    input("\n[엔터] 종료")
