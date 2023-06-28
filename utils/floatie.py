from dataclasses import dataclass
import requests
import json
from utils.config import config

class InnertubeError(Exception):
    pass

@dataclass
class InnertubeDetails:
    api_key: str
    client_version: str
    client_name: str
    android_version: str

innertube_details = InnertubeDetails(
    api_key="AIzaSyA8eiZmM1FaDVjRy-df2KTyQ_vz_yYM39w",
    client_version="17.31.35",
    client_name="3",
    android_version="12"
)

context = {
  "client": {
    "clientName": "ANDROID",
    "clientVersion": innertube_details.client_version,
    "androidSdkVersion": 31,
    "osName": "Android",
    "osVersion": innertube_details.android_version,
    "hl": "en",
    "gl": "US"
  }
}

def fetch_playback_urls(video_id: str) -> list[dict[str, str | int]]:
    url = f"https://www.youtube.com/youtubei/v1/player?key={innertube_details.api_key}"

    payload = json.dumps({
        "context": context,
        "videoId": video_id,
        "params": "8AEB",
        "playbackContext": {
            "contentPlaybackContext": {
                "html5Preference": "HTML5_PREF_WANTS"
            }
        },
        "contentCheckOk": True,
        "racyCheckOk": True
    })
    headers = {
        'X-Youtube-Client-Name': innertube_details.client_name,
        'X-Youtube-Client-Version': innertube_details.client_version,
        'Origin': 'https://www.youtube.com',
        'User-Agent': f'com.google.android.youtube/{innertube_details.client_version} (Linux; U; Android {innertube_details.android_version}) gzip',
        'Content-Type': 'application/json',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'en-us,en;q=0.5',
        'Sec-Fetch-Mode': 'navigate',
        'Connection': 'close'
    }
    proxies = {
        "http": config["proxy_url"],
        "https": config["proxy_url"]
    } if config["proxy_url"] is not None else None

    response = requests.request("POST", url, headers=headers, data=payload, proxies=proxies)
    if not response.ok:
        raise InnertubeError(f"Innertube failed with status code {response.status_code}")

    return response.json()["streamingData"]["adaptiveFormats"]