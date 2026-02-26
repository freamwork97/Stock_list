"""
스윙 매수 타점 모니터링 스크립트
지투파워, 셀바스헬스케어 2개 종목 집중 모니터링
"""
import subprocess
import csv
from pathlib import Path
from datetime import datetime


def run_analysis():
    """스윙 시그널 분석 실행"""
    print(f"[분석 시작] {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("-" * 60)

    result = subprocess.run(
        [
            "uv", "run", "python", "-m", "src.swing_signal",
            "--input", "output/monitor_targets.csv",
            "--out", "output/monitor_signals.csv",
        ],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        print("X 분석 실패:", result.stderr)
        return

    print(result.stdout)


def check_signals():
    """매수 시그널 확인"""
    signal_file = Path("output/monitor_signals.csv")
    if not signal_file.exists():
        return

    print("\n" + "=" * 60)
    print("[매수 타점 체크]")
    print("=" * 60)

    with signal_file.open("r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        buy_signals = []
        watch_list = []

        for row in reader:
            name = row["name"]
            signal = row["signal"] == "True"
            pullback = row["pullback_ok"] == "True"
            rebound = row["rebound_ok"] == "True"
            price = row["current_price"]
            retrace = row["retrace_pct"]
            vol_ratio = row["volume_ratio"]
            score = row["signal_score"]

            if signal:
                buy_signals.append(f">> {name} ({price}원) - 매수 진입 타점!")
            elif pullback and not rebound:
                watch_list.append(
                    f"   {name} ({price}원) - 눌림목 완료, 반등 대기 중"
                    f"\n   조정: {retrace}% | 거래량: {vol_ratio} | Score: {score}"
                )

    if buy_signals:
        print("\n[!!!] 매수 신호 발생! [!!!]")
        for signal in buy_signals:
            print(signal)
    else:
        print("\n아직 매수 타점 없음")

    if watch_list:
        print("\n[모니터링 중]")
        for item in watch_list:
            print(item)

    print("\n" + "=" * 60)


def main():
    run_analysis()
    check_signals()
    print("\n[안내] 매일 실행하여 매수 타점을 확인하세요!")
    print("       명령어: uv run python monitor.py")


if __name__ == "__main__":
    main()
