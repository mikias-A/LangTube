import json
from flask import Flask, request, jsonify, send_from_directory
from youtube_transcript_api import YouTubeTranscriptApi, NoTranscriptFound
import argostranslate.package
import argostranslate.translate

app = Flask(__name__, static_folder=".", static_url_path="")

SUPPORTED_LANGS = ("en", "es", "ko")
CACHE_FILE = "translation_cache.json"

original_cache = {}

try:
    with open(CACHE_FILE, "r", encoding="utf-8") as f:
        translation_cache = json.load(f)
except Exception:
    translation_cache = {}


class TranslateError(Exception):
    pass


def save_cache():
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(translation_cache, f, ensure_ascii=False)


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


def pair_ready(src, dst):
    langs = {l.code: l for l in argostranslate.translate.get_installed_languages()}
    if src not in langs or dst not in langs:
        return False
    return langs[src].get_translation(langs[dst]) is not None


def install_pair(src, dst):
    print(f"Downloading {src}-{dst} language pack (first time only)...", flush=True)
    argostranslate.package.update_package_index()
    for p in argostranslate.package.get_available_packages():
        if p.from_code == src and p.to_code == dst:
            argostranslate.package.install_from_path(p.download())
            print("Language pack installed.", flush=True)
            return True
    return False


def ensure_pair(src, dst):
    if pair_ready(src, dst):
        return
    if src == "en" or dst == "en":
        steps = [(src, dst)]
    else:
        steps = [(src, "en"), ("en", dst)]
    for a, b in steps:
        if not pair_ready(a, b) and not install_pair(a, b):
            raise TranslateError(f"No {a}-{b} pack")


def local_translate(texts, src, dst):
    if dst not in SUPPORTED_LANGS:
        raise TranslateError("Language not supported")
    ensure_pair(src, dst)
    print(f"Translating {len(texts)} captions into {dst}...", flush=True)
    results = []
    for n, text in enumerate(texts, 1):
        if text.strip():
            results.append(argostranslate.translate.translate(text, src, dst))
        else:
            results.append(text)
        if n % 50 == 0 or n == len(texts):
            print(f"Translated {n} of {len(texts)}", flush=True)
    return results


def get_cues(video_id, lang):
    cues, original_lang = get_original(video_id)
    src = original_lang.split("-")[0]
    if lang == src:
        return cues
    key = f"{video_id}|{lang}"
    if key not in translation_cache:
        translated = local_translate([c["text"] for c in cues], src, lang)
        translation_cache[key] = [
            {"start": c["start"], "end": c["end"], "text": text}
            for c, text in zip(cues, translated)
        ]
        save_cache()
        print("Translation done and saved.", flush=True)
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
    except TranslateError as e:
        print(f"Translation problem: {e}", flush=True)
        return jsonify(error=str(e), debug=str(e))
    except Exception as e:
        return jsonify(
            error="Couldn't load captions.",
            debug=f"{type(e).__name__}: {e}",
        )


if __name__ == "__main__":
    app.run(port=8000)
