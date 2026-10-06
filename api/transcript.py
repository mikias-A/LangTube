from http.server import BaseHTTPRequestHandler
import json
import re
import requests
from urllib.parse import urlparse, parse_qs

PROXY_USER = "hprytmcu"
PROXY_PASS = "7ls2auaubg3x"
PROXIES = {
    "http": f"http://{PROXY_USER}:{PROXY_PASS}@p.webshare.io:80/",
    "https": f"http://{PROXY_USER}:{PROXY_PASS}@p.webshare.io:80/",
}

ANDROID_USER_AGENT = "com.google.android.youtube/19.29.37 (Linux; U; Android 11) gzip"
INNERTUBE_KEY = "AIzaSyA8eiZmM1FaDVjRy-df2KTyQ_vz_yYM39w"

def fetch_captions(video_id):
    debug = {}

    player_res = requests.post(
        f"https://www.youtube.com/youtubei/v1/player?key={INNERTUBE_KEY}",
        proxies=PROXIES,
        timeout=10,
        headers={
            "Content-Type": "application/json",
            "User-Agent": ANDROID_USER_AGENT,
            "X-YouTube-Client-Name": "3",
            "X-YouTube-Client-Version": "19.29.37",
        },
        json={
            "videoId": video_id,
            "context": {
                "client": {
                    "clientName": "ANDROID",
                    "clientVersion": "19.29.37",
                    "androidSdkVersion": 30,
                    "userAgent": ANDROID_USER_AGENT,
                    "hl": "en",
                    "gl": "US",
                }
            },
        },
    )

    data = player_res.json()
    debug["playerStatus"] = player_res.status_code
    debug["hasCaptions"] = "captions" in data

    tracks = (
        data.get("captions", {})
        .get("playerCaptionsTracklistRenderer", {})
        .get("captionTracks", [])
    )

    if not tracks:
        debug["playabilityStatus"] = data.get("playabilityStatus", {}).get("status")
        return None, debug

    track = next((t for t in tracks if t.get("languageCode") == "en"), tracks[0])
    base_url = track["baseUrl"]

    cap_res = requests.get(base_url, proxies=PROXIES, timeout=10,
                            headers={"User-Agent": ANDROID_USER_AGENT})
    xml = cap_res.text
    debug["capStatus"] = cap_res.status_code
    debug["capBodyLength"] = len(xml)

    cues = []
    for m in re.finditer(r'<text start="([\d.]+)" dur="([\d.]+)"[^>]*>([^<]*)</text>', xml):
        clean = (
            m.group(3)
            .replace("&#39;", "'")
            .replace("&amp;", "&")
            .replace("&quot;", '"')
        )
        start = float(m.group(1))
        dur = float(m.group(2))
        cues.append({"start": start, "end": start + dur, "text": clean})

    return cues, debug


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        query = parse_qs(urlparse(self.path).query)
        video_id = query.get("videoId", [None])[0]

        self.send_response(200)
        self.send_header("Content-type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

        if not video_id:
            self.wfile.write(json.dumps({"error": "Missing videoId"}).encode())
            return

        try:
            cues, debug = fetch_captions(video_id)
            if not cues:
                self.wfile.write(json.dumps({
                    "error": "No captions found for this video.",
                    "debug": debug
                }).encode())
            else:
                self.wfile.write(json.dumps({"cues": cues}).encode())
        except Exception as e:
            self.wfile.write(json.dumps({
                "error": "Couldn't load captions.",
                "debug": str(e)
            }).encode())
        return
