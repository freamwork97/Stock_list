import argparse
import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from .client import KiwoomClient, parse_price


@dataclass
class StockRow:
    code: str
    name: str
    price: float | None
    volume: int | None
    change_rate: float | None
    swing_score: float | None = None


def to_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(float(str(value).replace(",", "")))
    except ValueError:
        return None


def to_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(str(value).replace(",", ""))
    except ValueError:
        return None


def parse_row(item: dict[str, Any]) -> StockRow:
    code = str(
        item.get("stk_cd")
        or item.get("code")
        or item.get("item_cd")
        or item.get("isu_cd")
        or ""
    ).strip()
    name = str(
        item.get("stk_nm")
        or item.get("name")
        or item.get("item_nm")
        or item.get("isu_nm")
        or ""
    ).strip()
    price_raw = (
        item.get("cur_prc")
        or item.get("cur_price")
        or item.get("stck_prpr")
        or item.get("price")
    )
    volume_raw = (
        item.get("acml_vol")
        or item.get("trde_qty")
        or item.get("now_trde_qty")
        or item.get("volume")
    )
    change_raw = item.get("flu_rt") or item.get("prdy_ctrt") or item.get("change_rate")

    return StockRow(
        code=code,
        name=name,
        price=parse_price(price_raw) if price_raw is not None else None,
        volume=to_int(volume_raw),
        change_rate=to_float(change_raw),
    )


def extract_items(response: dict[str, Any], mode: str) -> list[dict[str, Any]]:
    if not isinstance(response, dict):
        return []

    if mode == "volume":
        keys = ["tdy_trde_qty_upper", "output", "items"]
    elif mode == "change":
        keys = ["pred_pre_flu_rt_upper", "output", "items"]
    else:
        keys = ["condition_item_list", "stk_list", "output", "items"]

    for key in keys:
        value = response.get(key)
        if isinstance(value, list):
            return [x for x in value if isinstance(x, dict)]

    body = response.get("body", {})
    if not isinstance(body, dict):
        return []
    for key in keys:
        value = body.get(key)
        if isinstance(value, list):
            return [x for x in value if isinstance(x, dict)]
    return []


def filter_rows(
    rows: list[StockRow],
    keyword: str | None,
    min_price: float | None,
    max_price: float | None,
    min_volume: int | None,
) -> list[StockRow]:
    key = keyword.lower() if keyword else None
    result: list[StockRow] = []

    for row in rows:
        if key and key not in row.code.lower() and key not in row.name.lower():
            continue
        if min_price is not None and (row.price is None or row.price < min_price):
            continue
        if max_price is not None and (row.price is None or row.price > max_price):
            continue
        if min_volume is not None and (row.volume is None or row.volume < min_volume):
            continue
        result.append(row)
    return result


def get_rows_by_mode(client: KiwoomClient, mode: str, condition_idx: str | None) -> list[StockRow]:
    if mode == "volume":
        response = client.get_volume_rank()
    elif mode == "change":
        response = client.get_change_rate_rank()
    else:
        if not condition_idx:
            raise ValueError("--mode condition 사용 시 --condition-idx 가 필요합니다.")
        response = client.search_by_condition(condition_idx)

    if response.get("return_code") not in (None, 0):
        msg = response.get("return_msg", "API request failed")
        raise RuntimeError(f"Kiwoom API error: {msg}")

    return [parse_row(item) for item in extract_items(response, mode)]


def build_swing_rows(
    volume_rows: list[StockRow],
    change_rows: list[StockRow],
    min_change: float,
    max_change: float,
) -> list[StockRow]:
    vol_map = {x.code: x for x in volume_rows if x.code}
    chg_map = {x.code: x for x in change_rows if x.code}
    common_codes = set(vol_map.keys()) & set(chg_map.keys())
    if not common_codes:
        return []

    vol_rank = {r.code: i for i, r in enumerate(sorted(volume_rows, key=lambda x: x.volume or 0, reverse=True))}
    chg_rank = {r.code: i for i, r in enumerate(sorted(change_rows, key=lambda x: x.change_rate or -999.0, reverse=True))}

    rows: list[StockRow] = []
    for code in common_codes:
        v = vol_map[code]
        c = chg_map[code]
        if c.change_rate is None:
            continue
        if c.change_rate < min_change or c.change_rate > max_change:
            continue

        vr = vol_rank.get(code, 999)
        cr = chg_rank.get(code, 999)
        score = (1.0 / (vr + 1)) * 0.6 + (1.0 / (cr + 1)) * 0.4

        rows.append(
            StockRow(
                code=code,
                name=v.name or c.name,
                price=v.price if v.price is not None else c.price,
                volume=v.volume if v.volume is not None else c.volume,
                change_rate=c.change_rate,
                swing_score=score,
            )
        )

    rows.sort(key=lambda x: (x.swing_score or 0.0), reverse=True)
    return rows


def write_csv(path: str, rows: list[StockRow]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["code", "name", "price", "volume", "change_rate", "swing_score"])
        for r in rows:
            writer.writerow([r.code, r.name, r.price, r.volume, r.change_rate, r.swing_score])


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Kiwoom REST API stock list extractor")
    parser.add_argument(
        "--mode",
        choices=["volume", "change", "condition", "swing"],
        default="volume",
        help="volume/change/condition/swing(1주 스윙용 교집합 추천)",
    )
    parser.add_argument("--condition-idx", help="condition mode에서 사용할 조건식 번호")
    parser.add_argument("--keyword", help="종목코드/종목명 포함 문자열")
    parser.add_argument("--min-price", type=float, help="최소 현재가")
    parser.add_argument("--max-price", type=float, help="최대 현재가")
    parser.add_argument("--min-volume", type=int, help="최소 거래량")
    parser.add_argument("--limit", type=int, default=50, help="출력 개수 제한")
    parser.add_argument("--out", help="결과 CSV 저장 경로 (예: output/weekly_candidates.csv)")
    parser.add_argument("--swing-min-change", type=float, default=-3.0, help="swing 모드 최소 등락률(%)")
    parser.add_argument("--swing-max-change", type=float, default=12.0, help="swing 모드 최대 등락률(%)")
    return parser.parse_args()


def print_rows(mode: str, rows: list[StockRow], limit: int) -> None:
    print(f"mode={mode} total={len(rows)}")
    if mode == "swing":
        print("code\tname\tprice\tvolume\tchange_rate\tswing_score")
        for row in rows[:limit]:
            print(
                f"{row.code}\t{row.name}\t{row.price}\t{row.volume}\t"
                f"{row.change_rate}\t{row.swing_score:.6f}"
            )
    else:
        print("code\tname\tprice\tvolume\tchange_rate")
        for row in rows[:limit]:
            print(f"{row.code}\t{row.name}\t{row.price}\t{row.volume}\t{row.change_rate}")


def main() -> None:
    load_dotenv()
    args = parse_args()
    client = KiwoomClient()

    try:
        if args.mode == "swing":
            volume_rows = get_rows_by_mode(client, "volume", None)
            change_rows = get_rows_by_mode(client, "change", None)
            rows = build_swing_rows(
                volume_rows=volume_rows,
                change_rows=change_rows,
                min_change=args.swing_min_change,
                max_change=args.swing_max_change,
            )
        else:
            rows = get_rows_by_mode(client, args.mode, args.condition_idx)

        filtered = filter_rows(
            rows=rows,
            keyword=args.keyword,
            min_price=args.min_price,
            max_price=args.max_price,
            min_volume=args.min_volume,
        )

        print_rows(args.mode, filtered, args.limit)
        if args.out:
            write_csv(args.out, filtered)
            print(f"saved: {args.out}")
    except Exception as e:
        print(f"error: {e}")
        if args.mode == "condition":
            print(
                "hint: 조건검색은 /api/dostk/websocket 경로를 사용하며, "
                "모의투자에서는 미지원으로 실패할 수 있습니다."
            )
    finally:
        client.close()


if __name__ == "__main__":
    main()
