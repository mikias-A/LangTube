from http.server import BaseHTTPRequestHandler
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api.proxies import WebshareProxyConfig
import json
from urllib.parse import urlparse, parse_qs

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        query = parse_qs(urlparse(self.path).query)
        video_id = query.get('videoId', [None])[0]

        self.send_response(200)
        self.send_header('Content-type', 'application/json')
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()

        if not video_id:
            self.wfile.write(json.dumps({"error": "Missing videoId"}).encode())
            return

        try:
            ytt_api = YouTubeTranscriptApi(
                proxy_config=WebshareProxyConfig(
                    proxy_username="hprytmcu",
                    proxy_password="7ls2auaubg3x",
                )
            )
            transcript = ytt_api.fetch(video_id)
            cues = [
                {"start": snippet.start, "end": snippet.start + snippet.duration, "text": snippet.text}
                for snippet in transcript
            ]
            self.wfile.write(json.dumps({"cues": cues}).encode())
        except Exception as e:
            self.wfile.write(json.dumps({"error": "Couldn't load captions.", "debug": str(e)}).encode())
        return
