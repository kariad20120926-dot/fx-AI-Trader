"""src/utils/config.py — アプリケーション設定"""
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    env: str = "development"
    log_level: str = "DEBUG"
    api_port: int = 8080

    # OANDA
    oanda_api_key: str = ""
    oanda_account_id: str = ""
    oanda_environment: str = "practice"

    # GCP
    gcp_project_id: str = ""
    gcp_region: str = "asia-northeast1"

    # 取引設定
    trade_symbol: str = "USD_JPY"
    trade_timeframe: str = "H1"
    max_position_size: float = 0.01
    risk_per_trade: float = 0.02

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
