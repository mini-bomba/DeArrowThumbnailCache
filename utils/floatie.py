import json
import logging
from urllib import parse as urlp

import requests

from .config import get_config
from .logger import create_log_file
from .nsig import NsigHelper

config = get_config()
logger = logging.getLogger("utils.floatie")


class InnertubeError(Exception):
    pass


class InnertubePlayabilityError(Exception):
    pass


class InnertubeLoginRequiredError(Exception):
    pass


USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36 GLS/100.10.9939.100,gzip(gfe)"

context = {
  "client": {
    "browserName": "Chrome",
    "browserVersion": "125.0.0.0",
    "clientName": "WEB",
    "clientVersion": "2.20240808.00.00",
    "osName": "Windows",
    "osVersion": "10.0",
    "platform": "DESKTOP",
    "hl": "en",
    "gl": "US",
    "userAgent": USER_AGENT,
  }
}

if config.yt_auth.visitor_data is not None:
    context["client"]["visitorData"] = config.yt_auth.visitor_data.replace('=', '%3D')


def fetch_playback_urls(video_id: str, proxy_url: str | None) -> list[dict[str, str | int]]:
    url = "https://www.youtube.com/youtubei/v1/player?prettyPrint=false"
    nh = NsigHelper.get_instance()
    if config.yt_auth.nsig_helper.max_player_age < nh.player_update_timestamp():
        nh.force_update()

    payload = {
        "context": context,
        "videoId": video_id,
        "playbackContext": {
            "contentPlaybackContext": {
                "html5Preference": "HTML5_PREF_WANTS",
                "signatureTimestamp": nh.get_signature_timestamp(),
            }
        },
        "contentCheckOk": True,
        "racyCheckOk": True,
        # https://github.com/iv-org/invidious/pull/4789/files#diff-3919f4375b028c051402e6e79ae426d16da8fc4db65b4dfa945c384d00132870
        "params": "2AMB",
    }
    headers = {
        'X-Youtube-Client-Name': '1',
        'X-Youtube-Client-Version': '2.20240808.00.00',
        'Origin': 'https://www.youtube.com',
        'User-Agent': USER_AGENT,
        'Content-Type': 'application/json',
        'Accept': '*/*',
        'Accept-Language': 'en-us,en;q=0.5',
        'Sec-Fetch-Mode': 'navigate',
        'Connection': 'close'
    }
    cookies = {}

    if config.yt_auth.visitor_data is not None:
        headers['X-Goog-Visitor-Id'] = config.yt_auth.visitor_data.replace('=', '%3D')
        payload['serviceIntegrityDimensions'] = {"poToken": config.yt_auth.po_token}

    proxies = {
        "http": proxy_url,
        "https": proxy_url
    } if proxy_url is not None else None

    if proxy_url:
        logger.debug(f"Using proxy {proxy_url}")

    response = requests.request("POST", url, headers=headers, json=payload, proxies=proxies, cookies=cookies, timeout=10)
    if not response.ok:
        raise InnertubeError(f"Innertube failed with status code {response.status_code}")

    data = response.json()

    playability_status = data["playabilityStatus"]["status"]
    if playability_status != "OK":
        if playability_status == "LOGIN_REQUIRED":
            raise InnertubeLoginRequiredError(f"Login required: {data['playabilityStatus'].get('reason', 'no reason')}")
        else:
            raise InnertubePlayabilityError(f"Not Playable: {data['playabilityStatus']['status']}")

    if data["videoDetails"]["videoId"] != video_id:
        raise InnertubeError(f"Innertube returned wrong video ID: {data['videoDetails']['videoId']} vs. {video_id}")

    formats = data["streamingData"]["adaptiveFormats"]
    for adaptive_format in formats:
        url = None
        query = None
        if 'signatureCipher' in adaptive_format:
            cipher_params = urlp.parse_qs(adaptive_format['signatureCipher'])
            url = list(urlp.urlparse(cipher_params["url"][0]))
            query = urlp.parse_qs(url[4])
            query[cipher_params['sp'][0]] = [nh.decrypt_sig(cipher_params['s'][0])]
        elif 'url' in adaptive_format:
            url = list(urlp.urlparse(adaptive_format["url"]))
            query = urlp.parse_qs(url[4])

        if url is None:
            log = create_log_file("floatie-sussy-format", ext="json")
            logging.warning(f"A format was missing an url parameter. Dumping data to {log}")
            with log.open("w") as f:
                json.dump(adaptive_format, f, indent=2)
            continue

        if config.yt_auth.po_token is not None:
            query["pot"] = [config.yt_auth.po_token]
        if 'n' in query:
            query['n'] = [nh.decrypt_nsig(query['n'][0])]
        url[4] = urlp.urlencode(query, doseq=True)
        adaptive_format["url"] = urlp.urlunparse(url)

    return formats
