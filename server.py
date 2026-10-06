from flask import Flask, request, jsonify, send_from_directory
from youtube_transcript_api import YouTubeTranscriptApi, NoTranscriptFound

app = Flask(__name__, static_folder=".", static_url_path="")


def pick_transcript(video_id, lang):
    transcript_list = YouTubeTranscriptApi().list(video_id)
    try:
        return transcript_list.find_transcript([lang])
    except NoTranscriptFound:
        pass
    try:
        base = transcript_list.find_transcript(["en"])
    except NoTranscriptFound:
        base = next(iter(transcript_list))
    if base.is_translatable:
        return base.translate(lang)
    return base


@app.route("/")
def index():
    return send_from_directory(".", "index.html")


@app.route("/api/transcript")
def transcript():
    video_id = request.args.get("videoId")
    lang = request.args.get("lang", "en")
    if not video_id:
        return jsonify(error="Missing videoId")
    try:
        t = pick_transcript(video_id, lang).fetch()
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
