from http.server import BaseHTTPRequestHandler
from youtube_transcript_api import YouTubeTranscriptApi
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
            transcript = YouTubeTranscriptApi.get_transcript(video_id)
            cues = [
                {"start": item['start'], "end": item['start'] + item['duration'], "text": item['text']}
                for item in transcript
            ]
            self.wfile.write(json.dumps({"cues": cues}).encode())
        except Exception as e:
            self.wfile.write(json.dumps({"error": "Couldn't load captions.", "debug": str(e)}).encode())
        return
