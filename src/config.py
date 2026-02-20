from dataclasses import dataclass
import os


@dataclass
class KiwoomConfig:
    app_key: str
    app_secret: str
    account_no: str
    is_paper: bool
    base_url: str

    @classmethod
    def from_env(cls) -> "KiwoomConfig":
        env_name = os.getenv("KIWOOM_ENV", "paper").strip().lower()
        is_paper = env_name == "paper"

        if is_paper:
            app_key = os.getenv("KIWOOM_PAPER_APP_KEY", "").strip()
            app_secret = os.getenv("KIWOOM_PAPER_APP_SECRET", "").strip()
            account_no = os.getenv("KIWOOM_PAPER_ACCOUNT_NO", "").strip()
            default_base_url = "https://mockapi.kiwoom.com"
        else:
            app_key = os.getenv("KIWOOM_APP_KEY", "").strip()
            app_secret = os.getenv("KIWOOM_APP_SECRET", "").strip()
            account_no = os.getenv("KIWOOM_ACCOUNT_NO", "").strip()
            default_base_url = "https://api.kiwoom.com"

        base_url = os.getenv("KIWOOM_BASE_URL", default_base_url).strip() or default_base_url

        if not app_key or not app_secret:
            raise ValueError("Missing Kiwoom API credentials in .env")

        return cls(
            app_key=app_key,
            app_secret=app_secret,
            account_no=account_no,
            is_paper=is_paper,
            base_url=base_url,
        )
