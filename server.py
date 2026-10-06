from concurrent.futures import ThreadPoolExecutor
from flask import Flask, request, jsonify, send_from_directory
from youtube_transcript_api import YouTubeTranscriptApi, NoTranscriptFound
from deep_translator import GoogleTranslator

app = Flask(__name__, static_folder=".", static_url_path="")

original_cache = {}
translation_cache = {}


def get_original(video_id):
    if video_id in original_cache:
        return original_cache[video_id]
    print("Fetching captions from YouTube...", flush=True)
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
    print(f"Got {len(cues)} captions.", flush=True)
    original_cache[video_id] = (cues, t.language_code)
    return original_cache[video_id]


def translate_one(translator, text):
    if not text.strip():
        return text
    try:
        return translator.translate(text) or text
    except Exception:
        return text


def make_chunks(texts):
    chunks = []
    current = []
    size = 0
    for t in texts:
        t = t[:4000]
        if current and size + len(t) + 1 > 4000:
            chunks.append(current)
            current = []
            size = 0
        current.append(t)
        size += len(t) + 1
    if current:
        chunks.append(current)
    return chunks


def translate_chunk(chunk, lang):
    translator = GoogleTranslator(source="auto", target=lang)
    try:
        parts = (translator.translate("\n".join(chunk)) or "").split("\n")
        if len(parts) == len(chunk):
            return parts
    except Exception:
        pass
    return [translate_one(translator, t) for t in chunk]


def translate_texts(texts, lang):
    chunks = make_chunks(texts)
    print(f"Translating into {lang} in {len(chunks)} chunks...", flush=True)
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(lambda c: translate_chunk(c, lang), chunks))
    print("Translation done.", flush=True)
    return [t for part in results for t in part]


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
