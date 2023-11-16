import json
from dataclasses import dataclass
import re

import pydantic
import requests
from .config import get_config
import time
import random
from .redis_handler import redis_conn
from typing import Any

config = get_config()

def get_wait_period() -> int:
    return random.randint(15, 60) * 60

def fetch_proxies() -> list[Any]:
    if config.proxy_token is None:
        return []

    next_wait_period = float(redis_conn.get("next_proxy_fetch") or 0)
    last_fetch = float(redis_conn.get("last_proxy_fetch") or 0)
    if time.time() - last_fetch > next_wait_period:
        redis_conn.set("next_proxy_fetch", get_wait_period())
        redis_conn.set("last_proxy_fetch", time.time())

        response = requests.get(
            "https://proxy.webshare.io/api/v2/proxy/list/?mode=direct&page=1&page_size=100&ordering=-valid",
            headers={"Authorization": config.proxy_token}
        )

        result = response.json()
        if "results" in result:
            proxies = [result for result in result["results"] if result["valid"]]
            redis_conn.set("proxies", json.dumps(proxies))

            return proxies
        else:
            # Wait a minute for the rate limit to clear
            redis_conn.set("next_proxy_fetch", 60)

    return json.loads(redis_conn.get("proxies") or "[]")

def verify_proxy_url(url: str) -> bool:
    try:
        pydantic.HttpUrl(url)
        return True
    except pydantic.ValidationError:
        return False


@dataclass
class ProxyInfo:
    url: str
    country_code: str | None

def get_proxy_url() -> ProxyInfo | None:
    if config.proxy_token is None:
        if config.proxy_urls is not None:
            chosen_proxy = random.choice(config.proxy_urls)
            return ProxyInfo(str(chosen_proxy.url), chosen_proxy.country_code)
        else:
            return None

    proxies = fetch_proxies()

    if len(proxies) == 0:
        raise ValueError("No proxies available at the moment")
    else:
        chosen_proxy = proxies[random.randint(0, len(proxies) - 1)]
        url = f'http://{chosen_proxy["username"]}:{chosen_proxy["password"]}@{chosen_proxy["proxy_address"]}:{chosen_proxy["port"]}/'
        if verify_proxy_url(url):
            return ProxyInfo(url, chosen_proxy["country_code"])
        else:
            raise ValueError(f"Proxy url is invalid {url}")
