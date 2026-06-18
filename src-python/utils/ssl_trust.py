# -*- coding: utf-8 -*-
"""
utils/ssl_trust.py — OS 証明書ストアを Python の SSL に注入する

プロキシ/SSLインスペクション環境では certifi バンドルに無いローカル CA が
使われるため、requests 等が CERTIFICATE_VERIFY_FAILED になる。
truststore で Windows 証明書ストアを使うことで解消する。
"""
from __future__ import annotations

from utils.logger import get_logger

logger = get_logger(__name__)

_injected = False


def ensure_truststore() -> bool:
    """truststore を SSL に注入する（冪等）。未インストールなら False。"""
    global _injected
    if _injected:
        return True
    try:
        import truststore
        truststore.inject_into_ssl()
        _injected = True
        logger.debug("truststore 注入完了（OS証明書ストアを使用）")
        return True
    except ImportError:
        logger.debug("truststore 未インストール（certifi のみ使用）")
        return False
    except Exception as e:
        logger.warning(f"truststore 注入失敗: {e}")
        return False
