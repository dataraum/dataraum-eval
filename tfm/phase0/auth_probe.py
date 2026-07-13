"""DAT-742: boolean-only probe of the TabPFN auth chain. Never prints the token."""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

from tabpfn.browser_auth import (  # noqa: E402
    _get_license_name,
    check_license_accepted,
    get_cached_token,
    verify_token,
)
from tabpfn.settings import settings  # noqa: E402

print(f"env var set: {bool(os.environ.get('TABPFN_TOKEN'))}")
token = get_cached_token()
print(f"token found by tabpfn: {token is not None}")
if token:
    api_url = settings.tabpfn.auth_api_url
    print(f"token valid: {verify_token(token, api_url)}")
    lic = _get_license_name("tabpfn_3")
    print(f"license name for tabpfn_3: {lic}")
    print(f"license accepted: {check_license_accepted(token, api_url, lic)}")
