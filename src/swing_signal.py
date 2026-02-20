import argparse
import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from .client import KiwoomClient, parse_price


@dataclass
class SignalRow:
    code: str
    name: str
    current_price: float
    retrace_pct: float
    short_ma: float
    long_ma: float
    volume_ratio: float
    pullback_ok: bool
    rebound_ok: bool
    signal: bool
    signal_score: float


def to_int(value: Any) -> int:
    if value is None or value == "":
        return 0
    try:
        return int(float(str(value).replace(",", "")))
    except ValueError:
        return 0


def read_candidates(path: str) -> list[dict[str, str]]:
    with Path(path).open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        return [row for row in reader if row.get("code")]


def extract_chart_items(response: dict[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(response, dict):
        return []
    for key in ("stk_min_pole_chart_qry", "stk_tic_stk_pc_chrt", "output", "items"):
        value = response.get(key)
        if isinstance(value, list):
            return [x for x in value if isinstance(x, dict)]

    body = response.get("body", {})
    if isinstance(body, dict):
        for key in ("stk_tic_stk_pc_chrt", "output", "items"):
            value = body.get(key)
            if isinstance(value, list):
                return [x for x in value if isinstance(x, dict)]
    return []


def to_series(items: list[dict[str, Any]]) -> tuple[list[float], list[int]]:
    closes: list[float] = []
    volumes: list[int] = []
    for item in items:
        closes.append(
            parse_price(
                item.get("cur_prc")
                or item.get("stk_clsprc")
                or item.get("close")
                or 0
            )
        )
        volumes.append(to_int(item.get("trde_qty") or item.get("volume") or 0))
    return closes, volumes


def avg(values: list[float | int]) -> float:
    if not values:
        return 0.0
    return float(sum(values) / len(values))


def evaluate_signal(
    code: str,
    name: str,
    closes: list[float],
    volumes: list[int],
    recent_high_bars: int,
    pullback_min: float,
    pullback_max: float,
    min_vol_ratio: float,
) -> SignalRow | None:
    if len(closes) < 30:
        return None

    current = closes[-1]
    high_slice = closes[-recent_high_bars:] if len(closes) >= recent_high_bars else closes
    recent_high = max(high_slice)
    retrace = ((recent_high - current) / recent_high * 100) if recent_high > 0 else 0.0

    short_ma = avg(closes[-5:])
    long_ma = avg(closes[-20:])
    prev5_high = max(closes[-6:-1]) if len(closes) >= 6 else current

    recent_vol = avg(volumes[-5:])
    prev_vol = avg(volumes[-25:-5])
    vol_ratio = (recent_vol / prev_vol) if prev_vol > 0 else 0.0

    pullback_ok = pullback_min <= retrace <= pullback_max and (long_ma > 0 and current >= long_ma * 0.98)
    rebound_ok = current >= prev5_high and short_ma >= long_ma and vol_ratio >= min_vol_ratio
    signal = pullback_ok and rebound_ok
    score = 0.0
    score += 40.0 if pullback_ok else 0.0
    score += 40.0 if rebound_ok else 0.0
    score += min(20.0, max(0.0, (vol_ratio - 1.0) * 20.0))

    return SignalRow(
        code=code,
        name=name,
        current_price=current,
        retrace_pct=retrace,
        short_ma=short_ma,
        long_ma=long_ma,
        volume_ratio=vol_ratio,
        pullback_ok=pullback_ok,
        rebound_ok=rebound_ok,
        signal=signal,
        signal_score=score,
    )


def save_csv(path: str, rows: list[SignalRow]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "code",
                "name",
                "current_price",
                "retrace_pct",
                "short_ma",
                "long_ma",
                "volume_ratio",
                "pullback_ok",
                "rebound_ok",
                "signal",
                "signal_score",
            ]
        )
        for r in rows:
            writer.writerow(
                [
                    r.code,
                    r.name,
                    f"{r.current_price:.2f}",
                    f"{r.retrace_pct:.2f}",
                    f"{r.short_ma:.2f}",
                    f"{r.long_ma:.2f}",
                    f"{r.volume_ratio:.3f}",
                    r.pullback_ok,
                    r.rebound_ok,
                    r.signal,
                    f"{r.signal_score:.1f}",
                ]
            )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Pullback/rebound signal checker for weekly swing candidates")
    parser.add_argument("--input", default="output/weekly_candidates.csv", help="input CSV path")
    parser.add_argument("--tick-unit", default="1", help="minute tick unit for ka10080 (1/3/5/10...)")
    parser.add_argument("--limit", type=int, default=50, help="max rows to print")
    parser.add_argument("--out", default="output/weekly_signals.csv", help="output CSV path")
    parser.add_argument("--only-signal", action="store_true", help="print/save only signal=true rows")
    parser.add_argument("--recent-high-bars", type=int, default=120, help="high reference bars for pullback check")
    parser.add_argument("--pullback-min", type=float, default=3.0, help="minimum pullback percent")
    parser.add_argument("--pullback-max", type=float, default=15.0, help="maximum pullback percent")
    parser.add_argument("--min-vol-ratio", type=float, default=1.0, help="minimum recent/previous volume ratio")
    return parser.parse_args()


def main() -> None:
    load_dotenv()
    args = parse_args()
    candidates = read_candidates(args.input)
    client = KiwoomClient()

    try:
        rows: list[SignalRow] = []
        for row in candidates:
            code = str(row.get("code", "")).strip()
            name = str(row.get("name", "")).strip()
            if not code:
                continue

            response = client.get_stock_chart(code, tick_unit=args.tick_unit)
            if response.get("return_code") not in (None, 0):
                continue
            items = extract_chart_items(response)
            closes, volumes = to_series(items)
            evaluated = evaluate_signal(
                code,
                name,
                closes,
                volumes,
                recent_high_bars=args.recent_high_bars,
                pullback_min=args.pullback_min,
                pullback_max=args.pullback_max,
                min_vol_ratio=args.min_vol_ratio,
            )
            if evaluated is not None:
                rows.append(evaluated)

        rows.sort(key=lambda x: (x.signal, x.signal_score, x.volume_ratio), reverse=True)
        output_rows = [r for r in rows if r.signal] if args.only_signal else rows

        print(f"input={len(candidates)} analyzed={len(rows)} output={len(output_rows)}")
        print("code\tname\tprice\tretrace%\tvol_ratio\tpullback\trebound\tsignal\tscore")
        for r in output_rows[: args.limit]:
            print(
                f"{r.code}\t{r.name}\t{r.current_price:.2f}\t{r.retrace_pct:.2f}\t"
                f"{r.volume_ratio:.3f}\t{r.pullback_ok}\t{r.rebound_ok}\t{r.signal}\t{r.signal_score:.1f}"
            )

        save_csv(args.out, output_rows)
        print(f"saved: {args.out}")
    finally:
        client.close()


if __name__ == "__main__":
    main()
