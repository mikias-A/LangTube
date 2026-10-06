from flask import Flask, request, jsonify, send_from_directory
from youtube_transcript_api import YouTubeTranscriptApi

app = Flask(__name__, static_folder=".", static_url_path="")


@app.route("/")
def index():
    return send_from_directory(".", "index.html")


@app.route("/api/transcript")
def transcript():
    video_id = request.args.get("videoId")
    if not video_id:
        return jsonify(error="Missing videoId")
    try:
        t = YouTubeTranscriptApi().fetch(video_id, languages=["en", "es", "ko"])
        cues = [
            {"start": s.start, "end": s.start + s.duration, "text": s.text}
            for s in t
        ]
        return jsonify(cues=cues)
    except Exception as e:
        return jsonify(
            error="Couldn't load captions.",
            debug=f"{type(e).__name__}: {e}",
        )


if __name__ == "__main__":
    app.run(port=8000)
