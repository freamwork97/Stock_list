import time
from datetime import datetime

import FinanceDataReader as fdr
import numpy as np
import pandas as pd


def get_all_us_tickers():
    """미국 주요 거래소 종목 리스트"""
    try:
        sp500 = fdr.StockListing("S&P500")
        nasdaq = fdr.StockListing("NASDAQ")
        us_tickers = list(set(sp500["Symbol"].tolist() + nasdaq["Symbol"].tolist()))
        print(f"미국 종목 {len(us_tickers)}개 로드 완료")
        return us_tickers
    except Exception as e:
        print(f"미국 종목 리스트 로드 실패: {e}")
        return []


def get_all_korean_tickers():
    """한국 코스피/코스닥 전체 종목 리스트"""
    try:
        krx_df = fdr.StockListing("KRX")
        tickers = krx_df["Code"].tolist()
        kospi_count = len(krx_df[krx_df["Market"] == "KOSPI"])
        kosdaq_count = len(krx_df[krx_df["Market"] == "KOSDAQ"])
        print(
            f"한국 종목 {len(tickers)}개 (코스피 {kospi_count}, 코스닥 {kosdaq_count}) 로드 완료"
        )
        return tickers
    except Exception as e:
        print(f"한국 종목 리스트 로드 실패: {e}")
        return []


def calculate_bollinger_bands(df, period=20, std_dev=2):
    """볼린저 밴드 계산"""
    df["BB_Middle"] = df["Close"].rolling(window=period).mean()
    df["BB_Std"] = df["Close"].rolling(window=period).std()
    df["BB_Upper"] = df["BB_Middle"] + (std_dev * df["BB_Std"])
    df["BB_Lower"] = df["BB_Middle"] - (std_dev * df["BB_Std"])
    return df


def calculate_rsi(df, period=14):
    """RSI 계산"""
    delta = df["Close"].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    df["RSI"] = 100 - (100 / (1 + rs))
    return df


def calculate_ichimoku(df):
    """일목균형표 계산"""
    high_9 = df["High"].rolling(window=9).max()
    low_9 = df["Low"].rolling(window=9).min()
    df["Tenkan"] = (high_9 + low_9) / 2

    high_26 = df["High"].rolling(window=26).max()
    low_26 = df["Low"].rolling(window=26).min()
    df["Kijun"] = (high_26 + low_26) / 2

    df["SpanA"] = ((df["Tenkan"] + df["Kijun"]) / 2).shift(26)

    high_52 = df["High"].rolling(window=52).max()
    low_52 = df["Low"].rolling(window=52).min()
    df["SpanB"] = ((high_52 + low_52) / 2).shift(26)
    return df


def find_support_levels(df, lookback=52, tolerance=0.02):
    """지지선 찾기: 저점이 반복된 구간"""
    lows = df["Low"].tail(lookback).values
    lows = lows[~np.isnan(lows)]
    lows = lows[lows > 0]

    if len(lows) == 0:
        return []

    support_levels = []
    for current_low in lows:
        if current_low <= 0:
            continue
        nearby_lows = sum(
            1
            for low in lows
            if low > 0 and abs(low - current_low) / current_low < tolerance
        )
        if nearby_lows >= 3:
            support_levels.append({"price": current_low, "strength": nearby_lows})

    if support_levels:
        support_df = pd.DataFrame(support_levels)
        support_df = support_df.drop_duplicates(subset=["price"])
        support_df = support_df.sort_values("strength", ascending=False)
        return support_df.head(3)["price"].tolist()
    return []


def check_conditions(ticker):
    """종목별 조건 체크"""
    try:
        df = fdr.DataReader(ticker, start="2023-01-01")
        if df is None or len(df) < 52:
            return None

        df_weekly = (
            df.resample("W")
            .agg(
                {
                    "Open": "first",
                    "High": "max",
                    "Low": "min",
                    "Close": "last",
                    "Volume": "sum",
                }
            )
            .dropna()
        )
        if len(df_weekly) < 52:
            return None

        df_weekly = calculate_bollinger_bands(df_weekly)
        df_weekly = calculate_rsi(df_weekly)
        df_weekly = calculate_ichimoku(df_weekly)

        latest = df_weekly.iloc[-1]
        current_price = latest["Close"]
        conditions = {"ticker": ticker, "current_price": current_price, "checks": {}}

        bb_lower = latest["BB_Lower"]
        if pd.isna(bb_lower) or bb_lower == 0:
            return None
        bb_distance = (current_price - bb_lower) / bb_lower * 100
        conditions["checks"]["볼린저_하단"] = bb_distance <= 5
        conditions["bb_distance"] = f"{bb_distance:.2f}%"

        rsi = latest["RSI"]
        if pd.isna(rsi):
            return None
        conditions["checks"]["RSI_과매도"] = rsi <= 30
        conditions["rsi"] = f"{rsi:.2f}"

        support_levels = find_support_levels(df_weekly)
        near_support = any(
            support > 0 and abs(current_price - support) / support < 0.03
            for support in support_levels
        )
        conditions["checks"]["지지선_근처"] = near_support
        conditions["support_levels"] = (
            [f"{s:.0f}" for s in support_levels[:2]] if support_levels else []
        )

        span_a = latest["SpanA"]
        span_b = latest["SpanB"]
        near_cloud = False
        if not pd.isna(span_a) and not pd.isna(span_b) and span_a > 0 and span_b > 0:
            cloud_top = max(span_a, span_b)
            cloud_bottom = min(span_a, span_b)
            if cloud_bottom <= current_price <= cloud_top:
                near_cloud = True
            elif abs(current_price - cloud_bottom) / cloud_bottom < 0.05:
                near_cloud = True
            conditions["cloud_range"] = f"{cloud_bottom:.0f}~{cloud_top:.0f}"
        else:
            conditions["cloud_range"] = "N/A"
        conditions["checks"]["구름대_근처"] = near_cloud

        conditions["all_passed"] = all(conditions["checks"].values())
        conditions["passed_count"] = sum(conditions["checks"].values())
        return conditions
    except Exception:
        return None


def screen_stocks(tickers, min_conditions=3, show_errors=False):
    """종목 스크리닝"""
    results = []
    total = len(tickers)
    failed = 0
    error_reasons = {}

    print(f"\n총 {total}개 종목 분석 시작...")
    print(f"최소 {min_conditions}개 조건 통과 종목만 수집합니다.\n")

    for i, ticker in enumerate(tickers, 1):
        if i % 50 == 0:
            print(
                f"진행상황: {i}/{total} ({i/total*100:.1f}%) - "
                f"발견: {len(results)}개 실패: {failed}개"
            )
            if show_errors and error_reasons:
                print(f"  실패 원인: {dict(list(error_reasons.items())[:3])}")

        try:
            result = check_conditions(ticker)
            if result and result["passed_count"] >= min_conditions:
                results.append(result)
                print(
                    f"✅ {ticker}: {result['passed_count']}/4 조건 통과 "
                    f"(현재가: {result['current_price']:.0f}, RSI: {result['rsi']})"
                )
            elif result is None:
                failed += 1
                reason = "데이터 부족"
                error_reasons[reason] = error_reasons.get(reason, 0) + 1
        except Exception as e:
            failed += 1
            error_type = type(e).__name__
            error_reasons[error_type] = error_reasons.get(error_type, 0) + 1
            if show_errors and failed <= 5:
                print(f"❌ {ticker} 실패: {error_type} - {str(e)[:50]}")

        time.sleep(0.1)

    print(
        f"\n최종 통계: 총 {total}개 성공 {total-failed}개 실패 {failed}개 "
        f"조건충족 {len(results)}개"
    )
    if error_reasons:
        print("\n실패 원인 통계:")
        for reason, count in sorted(error_reasons.items(), key=lambda x: x[1], reverse=True):
            print(f"  - {reason}: {count}개")
    return results


def save_results(results, filename="screening_results.csv"):
    """결과를 CSV로 저장"""
    if not results:
        print("저장할 결과가 없습니다.")
        return

    df_list = []
    for r in results:
        df_list.append(
            {
                "종목코드": r["ticker"],
                "현재가": r["current_price"],
                "통과조건수": r["passed_count"],
                "RSI": r["rsi"],
                "볼린저하단대비": r["bb_distance"],
                "지지선": ", ".join(r["support_levels"]),
                "구름대범위": r["cloud_range"],
                "모든조건통과": "예" if r["all_passed"] else "아니오",
            }
        )

    df = pd.DataFrame(df_list)
    df = df.sort_values("통과조건수", ascending=False)
    df.to_csv(filename, index=False, encoding="utf-8-sig")
    print(f"\n결과가 '{filename}'에 저장되었습니다.")
    return df


def display_results(results):
    """결과 출력"""
    print("\n" + "=" * 80)
    print("스크리닝 결과")
    print("=" * 80 + "\n")

    all_passed = [r for r in results if r["all_passed"]]
    if all_passed:
        print(f"모든 조건(4개) 통과 종목: {len(all_passed)}개\n")
        for r in all_passed:
            print(f"  [{r['ticker']}] 현재가: {r['current_price']:.0f}")
            print(f"    - RSI: {r['rsi']}")
            print(f"    - 볼린저 하단 대비: {r['bb_distance']}")
            print(f"    - 지지선: {', '.join(r['support_levels'])}")
            print(f"    - 구름대: {r['cloud_range']}\n")

    partial_passed = [r for r in results if not r["all_passed"] and r["passed_count"] >= 3]
    if partial_passed:
        print(f"3개 조건 통과 종목: {len(partial_passed)}개\n")
        for r in partial_passed[:15]:
            passed = [k.replace("_", " ") for k, v in r["checks"].items() if v]
            print(f"  [{r['ticker']}] 현재가: {r['current_price']:.0f} ({r['passed_count']}/4)")
            print(f"    통과: {', '.join(passed)}")
            print(f"    RSI: {r['rsi']} | 볼린저: {r['bb_distance']}\n")
        if len(partial_passed) > 15:
            print(f"  ... 외 {len(partial_passed)-15}개 종목 (CSV 참고)")

    if not all_passed and not partial_passed:
        print("조건을 충족하는 종목이 없습니다.")
        print("조건을 완화하거나 다른 기간으로 다시 시도해보세요.")


if __name__ == "__main__":
    print("=" * 80)
    print("주봉 기반 종목 스크리닝 프로그램 (FinanceDataReader)")
    print("=" * 80)

    print("\n어떤 시장을 스크리닝하시겠습니까?")
    print("1. 한국 시장만 (코스피 + 코스닥)")
    print("2. 미국 시장만 (S&P500 + NASDAQ)")
    print("3. 한국 + 미국 전체")

    choice = input("\n선택 (1/2/3): ").strip()

    if choice == "1":
        tickers = get_all_korean_tickers()
    elif choice == "2":
        tickers = get_all_us_tickers()
    else:
        tickers = get_all_korean_tickers() + get_all_us_tickers()

    if not tickers:
        print("종목 리스트를 불러올 수 없습니다.")
        raise SystemExit(1)

    show_errors = (
        input("\n실패 종목의 에러를 표시하시겠습니까? (y/n, 기본:n): ").strip().lower()
        == "y"
    )

    results = screen_stocks(tickers, min_conditions=3, show_errors=show_errors)
    display_results(results)

    if results:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        save_results(results, f"screening_results_{timestamp}.csv")

    print(f"\n프로그램 종료. 총 {len(results)}개 종목이 조건을 충족했습니다.")
