#!/usr/bin/env python3
"""
GA4 Collector for BBagio Dashboard
Collects UV, sessions, traffic sources from GA4 Data API
Output: ga4_latest.json
"""

import json
import os
from datetime import datetime, timedelta
from pathlib import Path

# ── 설정 ────────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent
KEY_FILE = BASE_DIR / "ga4_service_account.json"
OUTPUT_FILE = BASE_DIR / "ga4_latest.json"

def _load_property_id():
    """config.json → ga4_property_id 우선, 환경변수 GA4_PROPERTY_ID 보조"""
    cfg_file = BASE_DIR / "config.json"
    if cfg_file.exists():
        try:
            cfg = json.loads(cfg_file.read_text(encoding="utf-8"))
            pid = cfg.get("ga4_property_id", "").strip()
            if pid:
                return pid
        except Exception:
            pass
    return os.environ.get("GA4_PROPERTY_ID", "").strip()

GA4_PROPERTY_ID = _load_property_id()
# ────────────────────────────────────────────────────────────────────────────


def get_client():
    """서비스 계정 JSON 키로 GA4 클라이언트 생성"""
    if not KEY_FILE.exists():
        raise FileNotFoundError(
            f"서비스 계정 키 파일이 없습니다: {KEY_FILE}\n"
            "ga4_service_account.json 을 이 폴더에 넣어주세요."
        )
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(KEY_FILE)

    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        from google.analytics.data_v1beta import BetaAnalyticsDataClient
    return BetaAnalyticsDataClient()


def run_report(client, date_ranges, dimensions, metrics, limit=10):
    """GA4 RunReport 공통 래퍼"""
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        from google.analytics.data_v1beta.types import (
            RunReportRequest, DateRange, Dimension, Metric
        )

    request = RunReportRequest(
        property=f"properties/{GA4_PROPERTY_ID}",
        date_ranges=[DateRange(**dr) for dr in date_ranges],
        dimensions=[Dimension(name=d) for d in dimensions],
        metrics=[Metric(name=m) for m in metrics],
        limit=limit,
    )
    return client.run_report(request)


def collect_overview(client, today_str, yesterday_str):
    """오늘 / 어제 기준 기본 지표: 세션, UV, PV, 이탈률"""
    response = run_report(
        client,
        date_ranges=[
            {"start_date": today_str,     "end_date": today_str},
            {"start_date": yesterday_str, "end_date": yesterday_str},
        ],
        dimensions=["date"],
        metrics=["sessions", "activeUsers", "screenPageViews", "bounceRate"],
        limit=2,
    )

    result = {}
    for row in response.rows:
        date_val = row.dimension_values[0].value
        result[date_val] = {
            "sessions":   int(row.metric_values[0].value or 0),
            "uv":         int(row.metric_values[1].value or 0),
            "pageviews":  int(row.metric_values[2].value or 0),
            "bounce_rate": round(float(row.metric_values[3].value or 0) * 100, 1),
        }
    return result


def collect_traffic_sources(client, start_date, end_date):
    """유입 채널별 세션 / UV"""
    response = run_report(
        client,
        date_ranges=[{"start_date": start_date, "end_date": end_date}],
        dimensions=["sessionDefaultChannelGroup"],
        metrics=["sessions", "activeUsers"],
        limit=20,
    )

    rows = []
    for row in response.rows:
        rows.append({
            "channel":  row.dimension_values[0].value,
            "sessions": int(row.metric_values[0].value or 0),
            "uv":       int(row.metric_values[1].value or 0),
        })

    # 세션 기준 정렬
    rows.sort(key=lambda x: x["sessions"], reverse=True)
    return rows


def collect_top_pages(client, start_date, end_date, limit=10):
    """페이지뷰 상위 N개"""
    response = run_report(
        client,
        date_ranges=[{"start_date": start_date, "end_date": end_date}],
        dimensions=["pagePath"],
        metrics=["screenPageViews", "activeUsers"],
        limit=limit,
    )

    rows = []
    for row in response.rows:
        rows.append({
            "page":      row.dimension_values[0].value,
            "pageviews": int(row.metric_values[0].value or 0),
            "uv":        int(row.metric_values[1].value or 0),
        })
    return rows


def collect_hourly_uv(client, date_str):
    """시간대별 UV (오늘 or 어제)"""
    response = run_report(
        client,
        date_ranges=[{"start_date": date_str, "end_date": date_str}],
        dimensions=["hour"],
        metrics=["activeUsers", "sessions"],
        limit=24,
    )

    hourly = {str(h).zfill(2): {"uv": 0, "sessions": 0} for h in range(24)}
    for row in response.rows:
        h = row.dimension_values[0].value.zfill(2)
        hourly[h] = {
            "uv":       int(row.metric_values[0].value or 0),
            "sessions": int(row.metric_values[1].value or 0),
        }
    return hourly


def collect_device_breakdown(client, start_date, end_date):
    """기기별 세션 비중 (mobile / desktop / tablet)"""
    response = run_report(
        client,
        date_ranges=[{"start_date": start_date, "end_date": end_date}],
        dimensions=["deviceCategory"],
        metrics=["sessions", "activeUsers"],
        limit=10,
    )

    rows = []
    for row in response.rows:
        rows.append({
            "device":   row.dimension_values[0].value,
            "sessions": int(row.metric_values[0].value or 0),
            "uv":       int(row.metric_values[1].value or 0),
        })
    return rows


def collect_7day_trend(client, end_date):
    """최근 7일간 일별 UV / 세션"""
    start_date = (datetime.strptime(end_date, "%Y-%m-%d") - timedelta(days=6)).strftime("%Y-%m-%d")
    response = run_report(
        client,
        date_ranges=[{"start_date": start_date, "end_date": end_date}],
        dimensions=["date"],
        metrics=["activeUsers", "sessions", "screenPageViews"],
        limit=7,
    )

    rows = []
    for row in response.rows:
        rows.append({
            "date":      row.dimension_values[0].value,
            "uv":        int(row.metric_values[0].value or 0),
            "sessions":  int(row.metric_values[1].value or 0),
            "pageviews": int(row.metric_values[2].value or 0),
        })
    rows.sort(key=lambda x: x["date"])
    return rows


def main():
    # ── 전제조건 확인 (미설정 시 조용히 종료, exit 0) ────────────────────
    if not GA4_PROPERTY_ID:
        print("⏭  GA4 수집 건너뜀: config.json의 ga4_property_id 미설정")
        print("   GA4 관리 → 속성 설정 → 속성 ID (숫자) 를 config.json에 입력하세요.")
        return

    if not KEY_FILE.exists():
        print(f"⏭  GA4 수집 건너뜀: {KEY_FILE.name} 없음")
        print("   Downloads 폴더의 marine-resource-*.json 을 이 폴더에 복사 후")
        print("   파일명을 ga4_service_account.json 으로 변경하세요.")
        return

    print(f"[GA4] Property ID : {GA4_PROPERTY_ID}")
    print(f"[GA4] Key file    : {KEY_FILE.name}")

    try:
        client = get_client()
    except Exception as e:
        print(f"⏭  GA4 클라이언트 초기화 실패: {e}")
        return

    today         = datetime.now()
    today_str     = today.strftime("%Y-%m-%d")
    yesterday_str = (today - timedelta(days=1)).strftime("%Y-%m-%d")
    week_start    = (today - timedelta(days=6)).strftime("%Y-%m-%d")

    print(f"[GA4] 데이터 수집 중... ({today_str})")

    try:
        # 1. 오늘/어제 기본 지표
        overview = collect_overview(client, today_str, yesterday_str)
        print("  ✓ 개요 지표")

        # 2. 유입 채널 (최근 7일)
        traffic_sources = collect_traffic_sources(client, week_start, today_str)
        print(f"  ✓ 유입 채널 {len(traffic_sources)}개")

        # 3. 상위 페이지 (최근 7일)
        top_pages = collect_top_pages(client, week_start, today_str, limit=10)
        print(f"  ✓ 상위 페이지 {len(top_pages)}개")

        # 4. 시간대별 UV (오늘)
        hourly_uv = collect_hourly_uv(client, today_str)
        print("  ✓ 시간대별 UV")

        # 5. 기기별 비중
        device_breakdown = collect_device_breakdown(client, week_start, today_str)
        print("  ✓ 기기별 분석")

        # 6. 최근 7일 트렌드
        trend_7day = collect_7day_trend(client, today_str)
        print("  ✓ 7일 트렌드")

        # ── 결과 저장 ──────────────────────────────────────────────────────
        result = {
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "property_id": GA4_PROPERTY_ID,
            "today": today_str,
            "yesterday": yesterday_str,
            "today_metrics": overview.get(today_str.replace("-", ""), {
                "sessions": 0, "uv": 0, "pageviews": 0, "bounce_rate": 0,
            }),
            "yesterday_metrics": overview.get(yesterday_str.replace("-", ""), {
                "sessions": 0, "uv": 0, "pageviews": 0, "bounce_rate": 0,
            }),
            "traffic_sources":  traffic_sources,
            "top_pages":        top_pages,
            "hourly_uv_today":  hourly_uv,
            "device_breakdown": device_breakdown,
            "trend_7day":       trend_7day,
        }

        OUTPUT_FILE.write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"\n✅ 저장: {OUTPUT_FILE}")

        td = result["today_metrics"]
        yd = result["yesterday_metrics"]
        print(f"📊 오늘: UV {td.get('uv',0):,}  세션 {td.get('sessions',0):,}  PV {td.get('pageviews',0):,}")
        print(f"📊 어제: UV {yd.get('uv',0):,}  세션 {yd.get('sessions',0):,}  PV {yd.get('pageviews',0):,}")
        if traffic_sources:
            top = traffic_sources[0]
            print(f"🔝 최고 유입: {top['channel']} ({top['sessions']:,} 세션)")

    except Exception as e:
        print(f"❌ GA4 수집 오류: {e}")
        import traceback; traceback.print_exc()


if __name__ == "__main__":
    main()
