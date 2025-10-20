from __future__ import annotations

import time
from typing import Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ko,en;q=0.9",
}


_SESSION: Optional[requests.Session] = None


def _get_session() -> requests.Session:
    global _SESSION
    if _SESSION is None:
        s = requests.Session()
        retries = Retry(
            total=3,
            backoff_factor=0.5,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET"],
        )
        adapter = HTTPAdapter(max_retries=retries)
        s.mount("http://", adapter)
        s.mount("https://", adapter)
        _SESSION = s
    return _SESSION


def http_get(url: str, timeout: int = 20) -> str:
    session = _get_session()
    resp = session.get(url, timeout=timeout, headers=DEFAULT_HEADERS)
    resp.raise_for_status()
    resp.encoding = resp.apparent_encoding or resp.encoding
    return resp.text


def get_workbook_url(company: str) -> Optional[str]:
    if company == "삼성":
        return "https://www.acmicpc.net/workbook/view/1152"
    if company == "카카오":
        return "https://www.acmicpc.net/workbook/view/22772"
    if company == "LG":
        return "https://www.acmicpc.net/workbook/view/16119"
    if company == "현대":
        return "https://www.acmicpc.net/workbook/view/18057"
    return None


def get_problem_url(problem_id: int) -> str:
    return f"https://www.acmicpc.net/problem/{problem_id}"


