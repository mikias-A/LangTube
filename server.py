from flask import Flask, request, jsonify, send_from_directory
from youtube_transcript_api import YouTubeTranscriptApi, NoTranscriptFound
from deep_translator import GoogleTranslator

app = Flask(__name__, static_folder=".", static_url_path="")

original_cache = {}
translation_cache = {}


def get_original(video_id):
    if video_id in original_cache:
        return original_cache[video_id]
    transcript_list = YouTubeTranscriptApi().list(video_id)
    try:
        t = transcript_list.find_transcript(["en"])
    except NoTranscriptFound:
        t = next(iter(transcript_list))
    fetched = t.fetch()
    cues = [
        {
            "start": s.start,
            "end": s.start + s.duration,
            "text": s.text.replace("\n", " "),
        }
        for s in fetched
    ]
    original_cache[video_id] = (cues, t.language_code)
    return original_cache[video_id]


def translate_one(translator, text):
    if not text.strip():
        return text
    try:
        return translator.translate(text) or text
    except Exception:
        return text


def translate_texts(texts, lang):
    translator = GoogleTranslator(source="auto", target=lang)
    results = []
    i = 0
    while i < len(texts):
        chunk = []
        size = 0
        while i < len(texts) and size + len(texts[i]) + 1 < 4000:
            chunk.append(texts[i])
            size += len(texts[i]) + 1
            i += 1
        if not chunk:
            chunk = [texts[i][:4000]]
            i += 1
        try:
            parts = (translator.translate("\n".join(chunk)) or "").split("\n")
        except Exception:
            parts = []
        if len(parts) != len(chunk):
            parts = [translate_one(translator, t) for t in chunk]
        results.extend(parts)
    return results


def get_cues(video_id, lang):
    cues, original_lang = get_original(video_id)
    if lang == original_lang or lang.split("-")[0] == original_lang.split("-")[0]:
        return cues
    key = (video_id, lang)
    if key not in translation_cache:
        translated = translate_texts([c["text"] for c in cues], lang)
        translation_cache[key] = [
            {"start": c["start"], "end": c["end"], "text": text}
            for c, text in zip(cues, translated)
        ]
    return translation_cache[key]


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
        return jsonify(cues=get_cues(video_id, lang))
    except Exception as e:
        return jsonify(
            error="Couldn't load captions.",
            debug=f"{type(e).__name__}: {e}",
        )


if __name__ == "__main__":
    app.run(port=8000)
