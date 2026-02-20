# Stock List (Kiwoom REST API + uv)

`src/main.py`는 `src/client.py`, `src/auth.py`를 사용해 Kiwoom REST API 종목 리스트를 조회합니다.

## 준비

```powershell
uv venv
.\.venv\Scripts\Activate.ps1
uv pip install -e .
Copy-Item .env.example .env
```

## 실행

거래량 상위(ka10030):

```powershell
uv run stock-list --mode volume --min-price 5000 --min-volume 100000 --limit 30
```

등락률 상위(ka10027):

```powershell
uv run stock-list --mode change --limit 30
```

조건검색 결과:

```powershell
uv run stock-list --mode condition --condition-idx 001 --limit 50
```

일주일 스윙용 후보 리스트(거래량/등락률 교집합 + 점수):

```powershell
uv run stock-list --mode swing --min-price 5000 --min-volume 300000 --limit 50 --out output/weekly_candidates.csv
```

일주일 스윙 후보에 대해 당일 눌림/재상승 신호 판정:

```powershell
uv run swing-signal --input output/weekly_candidates.csv --tick-unit 1 --only-signal --out output/weekly_signals.csv
```

조건검색(ka10171/ka10172)은 PDF 기준 URL이 `/api/dostk/websocket` 입니다.
모의투자 환경에서는 조건검색이 실패(코드 7/1999)할 수 있어 실전 환경에서 확인이 필요합니다.
`.env`에서 아래 값을 조정하세요.

- `KIWOOM_CONDITION_PATH`
- `KIWOOM_CONDITION_LIST_API_ID`
- `KIWOOM_CONDITION_SEARCH_API_ID`

## 출력 컬럼

- `code`, `name`, `price`, `volume`, `change_rate`
- `swing` 모드에서는 `swing_score` 추가

