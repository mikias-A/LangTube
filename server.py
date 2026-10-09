import json
import os
import re
import threading
from flask import Flask, request, jsonify, send_from_directory
from youtube_transcript_api import YouTubeTranscriptApi, NoTranscriptFound
import argostranslate.package
import argostranslate.settings
import argostranslate.translate

app = Flask(__name__, static_folder=".", static_url_path="")

SUPPORTED_LANGS = ("en", "es", "ko")
CACHE_FILE = "translation_cache_v3.json"
ORIGINAL_FILE = "original_cache_v2.json"
REPAIR_FILE = "pack_repairs_v3.json"
MAX_CHARS = 70
PAUSE_GAP = 1.0
SENTENCE_MAX = 240
EDGE_CHARS = ".,!?;:\"'()[]{}¿¡…—–-<>»«“”‘’*"
PRELOAD_PAIRS = [("en", "es"), ("en", "ko"), ("es", "en"), ("ko", "en")]
TEST_WORDS = {"en": "house", "es": "casa", "ko": "집"}
FRAMES = {"en": "Word: {}"}
PREFIX_RE = re.compile(r"^\s*(word|palabra|단어)s?\s*[:：]?\s*", re.IGNORECASE)

MARIAN_REPO = "michaelfeil/ct2fast-opus-mt-es-en"
MARIAN_DIR = os.path.join("models", "opus-mt-es-en")

NOUN_TAGS = {"NNG", "NNP", "NNB", "NR", "NP"}
PARTICLES = {
    "은": "topic marker",
    "는": "topic marker",
    "이": "subject marker",
    "가": "subject marker",
    "을": "object marker",
    "를": "object marker",
    "에": "at / to / in",
    "에서": "at / from",
    "에게": "to (a person)",
    "한테": "to (a person)",
    "께": "to (honorific)",
    "의": "'s (possessive)",
    "와": "and / with",
    "과": "and / with",
    "랑": "and / with",
    "이랑": "and / with",
    "도": "also",
    "만": "only",
    "부터": "from",
    "까지": "until / to",
    "으로": "by / toward",
    "로": "by / toward",
    "보다": "than",
    "처럼": "like",
    "마다": "every",
}
ENDINGS = {
    "고": "and / and then",
    "지만": "but",
    "는데": "background / but",
    "니까": "because",
    "으니까": "because",
    "아서": "so / because",
    "어서": "so / because",
    "면": "if",
    "으면": "if",
    "려고": "in order to",
    "게": "so that / -ly",
    "습니다": "formal polite ending",
    "ㅂ니다": "formal polite ending",
    "요": "polite ending",
    "았": "past tense",
    "었": "past tense",
    "겠": "will / intention",
    "시": "honorific",
    "기": "noun-maker",
    "음": "noun-maker",
}

pack_lock = threading.Lock()
marian_lock = threading.Lock()
kiwi_lock = threading.Lock()
marian_model = None
kiwi_obj = None
translators = {}
define_cache = {}
broken_pairs = set()


def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)


translation_cache = load_json(CACHE_FILE)
original_disk = load_json(ORIGINAL_FILE)
repaired = load_json(REPAIR_FILE)


class TranslateError(Exception):
    pass


class MarianTranslation:
    def __init__(self, folder):
        import ctranslate2
        import sentencepiece

        self.translator = ctranslate2.Translator(
            folder, device="cpu", compute_type="float32"
        )
        self.sp_src = sentencepiece.SentencePieceProcessor(
            os.path.join(folder, "source.spm")
        )
        self.sp_tgt = sentencepiece.SentencePieceProcessor(
            os.path.join(folder, "target.spm")
        )

    def translate(self, text):
        tokens = self.sp_src.encode(text, out_type=str) + ["</s>"]
        results = self.translator.translate_batch(
            [tokens], beam_size=4, max_decoding_length=256
        )
        return self.sp_tgt.decode_pieces(results[0].hypotheses[0])


def get_marian():
    global marian_model
    with marian_lock:
        if marian_model is not None:
            return marian_model
        if not os.path.exists(os.path.join(MARIAN_DIR, "model.bin")):
            print(
                "Downloading the Spanish -> English model (first time only, may take a few minutes)...",
                flush=True,
            )
            try:
                from huggingface_hub import snapshot_download

                snapshot_download(repo_id=MARIAN_REPO, local_dir=MARIAN_DIR)
            except Exception as e:
                print(f"Download problem: {e}", flush=True)
                raise TranslateError("Spanish model missing")
        marian_model = MarianTranslation(MARIAN_DIR)
        return marian_model


def get_kiwi():
    global kiwi_obj
    with kiwi_lock:
        if kiwi_obj is None:
            from kiwipiepy import Kiwi

            kiwi_obj = Kiwi()
        return kiwi_obj


def merge_cues(cues):
    merged = []
    current = None
    for c in cues:
        text = c["text"].strip()
        if not text:
            continue
        if current is None:
            current = {"start": c["start"], "end": c["end"], "text": text}
            continue
        gap = c["start"] - current["end"]
        too_long = len(current["text"]) + 1 + len(text) > MAX_CHARS
        sentence_ended = current["text"][-1] in ".?!"
        if sentence_ended or gap > PAUSE_GAP or too_long:
            merged.append(current)
            current = {"start": c["start"], "end": c["end"], "text": text}
        else:
            current["text"] += " " + text
            current["end"] = max(current["end"], c["end"])
    if current is not None:
        merged.append(current)
    return merged


def get_original(video_id):
    if video_id in original_disk:
        saved = original_disk[video_id]
        return saved["cues"], saved["lang"]
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
    cues = merge_cues(cues)
    print(f"Merged into {len(cues)} lines.", flush=True)
    original_disk[video_id] = {"cues": cues, "lang": t.language_code}
    save_json(ORIGINAL_FILE, original_disk)
    return cues, t.language_code


def is_garbage(text):
    return bool(re.search(r"(.{3,}?)\1{2,}", text.strip()))


def looks_broken(text):
    t = text.strip()
    if not t:
        return True
    if is_garbage(t):
        return True
    return len(t) > 60


def pair_ready(src, dst):
    langs = {l.code: l for l in argostranslate.translate.get_installed_languages()}
    if src not in langs or dst not in langs:
        return False
    return langs[src].get_translation(langs[dst]) is not None


def version_key(pkg):
    v = str(getattr(pkg, "package_version", "0"))
    return [int(x) for x in re.findall(r"\d+", v)] or [0]


def clear_cached_download(pkg):
    try:
        name = argostranslate.package.argospm_package_name(pkg) + ".argosmodel"
        path = argostranslate.settings.downloads_dir / name
        if path.exists():
            path.unlink()
            print(f"Deleted saved download {name}", flush=True)
    except Exception as e:
        print(f"Couldn't delete saved download: {e}", flush=True)


def available_matches(src, dst):
    argostranslate.package.update_package_index()
    return sorted(
        [
            p
            for p in argostranslate.package.get_available_packages()
            if p.from_code == src and p.to_code == dst
        ],
        key=version_key,
        reverse=True,
    )


def install_pair(src, dst):
    print(f"Downloading {src}-{dst} language pack...", flush=True)
    matches = available_matches(src, dst)
    if not matches:
        return False
    best = matches[0]
    argostranslate.package.install_from_path(best.download())
    print(f"Language pack {src}-{dst} installed.", flush=True)
    return True


def ensure_pair(src, dst):
    with pack_lock:
        if pair_ready(src, dst):
            return
        if src == "en" or dst == "en":
            steps = [(src, dst)]
        else:
            steps = [(src, "en"), ("en", dst)]
        for a, b in steps:
            if not pair_ready(a, b) and not install_pair(a, b):
                raise TranslateError(f"No {a}-{b} pack")


def get_translator(src, dst):
    key = (src, dst)
    if key in translators:
        return translators[key]
    if key == ("es", "en"):
        translators[key] = get_marian()
        return translators[key]
    ensure_pair(src, dst)
    langs = {l.code: l for l in argostranslate.translate.get_installed_languages()}
    translation = langs[src].get_translation(langs[dst])
    if translation is None:
        raise TranslateError(f"No {src}-{dst} pack")
    translators[key] = translation
    return translation


def remove_pair(src, dst):
    for pkg in argostranslate.package.get_installed_packages():
        if pkg.from_code == src and pkg.to_code == dst:
            argostranslate.package.uninstall(pkg)
    translators.pop((src, dst), None)


def check_pair(src, dst):
    try:
        out = get_translator(src, dst).translate(TEST_WORDS[src])
    except Exception as e:
        print(f"Check of {src} -> {dst} failed: {e}", flush=True)
        return False
    print(f"Check {src} -> {dst}: {TEST_WORDS[src]!r} -> {out[:60]!r}", flush=True)
    return not looks_broken(out)


def try_versions(src, dst):
    matches = available_matches(src, dst)
    for p in matches:
        ver = getattr(p, "package_version", "?")
        print(f"Trying {src}-{dst} pack version {ver} from a fresh download...", flush=True)
        with pack_lock:
            remove_pair(src, dst)
            clear_cached_download(p)
            argostranslate.package.install_from_path(p.download())
        if check_pair(src, dst):
            return True
    return False


def preload():
    print("Checking language packs (first run downloads them, about 100 MB each)...", flush=True)
    for src, dst in PRELOAD_PAIRS:
        try:
            if check_pair(src, dst):
                broken_pairs.discard((src, dst))
                print(f"{src} -> {dst} ready.", flush=True)
                continue
            if (src, dst) == ("es", "en"):
                broken_pairs.add((src, dst))
                print(
                    "es -> en model isn't working. Spanish word meanings will fall back to the English caption line.",
                    flush=True,
                )
                continue
            marker = f"{src}-{dst}"
            if marker in repaired:
                broken_pairs.add((src, dst))
                print(f"{src} -> {dst} still looks broken (already tried repairing it).", flush=True)
                continue
            print(f"{src} -> {dst} looks broken, trying every available version...", flush=True)
            ok = try_versions(src, dst)
            repaired[marker] = True
            save_json(REPAIR_FILE, repaired)
            if ok:
                broken_pairs.discard((src, dst))
                print(f"{src} -> {dst} repaired.", flush=True)
            else:
                broken_pairs.add((src, dst))
                print(f"{src} -> {dst} still broken. Restart the server once to be sure.", flush=True)
        except Exception as e:
            print(f"Problem with {src} -> {dst}: {e}", flush=True)
    try:
        get_kiwi()
        print("Korean word splitter ready.", flush=True)
    except Exception as e:
        print(
            f"Korean word splitter not available ({type(e).__name__}). Install it with: python -m pip install kiwipiepy",
            flush=True,
        )
    print("Language packs ready.", flush=True)


def clean_for_translation(text):
    text = re.sub(r">>+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def group_sentences(cues):
    groups = []
    current = []
    chars = 0
    for i, c in enumerate(cues):
        if current:
            prev = cues[current[-1]]
            gap = c["start"] - prev["end"]
            ended = prev["text"].rstrip()[-1:] in (".", "?", "!")
            if ended or gap > PAUSE_GAP or chars + len(c["text"]) > SENTENCE_MAX:
                groups.append(current)
                current = []
                chars = 0
        current.append(i)
        chars += len(c["text"]) + 1
    if current:
        groups.append(current)
    return groups


def spread(translated, texts):
    n = len(texts)
    if n == 1:
        return [translated.strip()]
    words = translated.split()
    total = sum(max(len(t), 1) for t in texts)
    parts = []
    used = 0
    running = 0
    for k, t in enumerate(texts):
        running += max(len(t), 1)
        if k == n - 1:
            end = len(words)
        else:
            end = round(len(words) * running / total)
        parts.append(" ".join(words[used:end]))
        used = end
    return parts


def translate_cues(cues, src, dst):
    if dst not in SUPPORTED_LANGS:
        raise TranslateError("Language not supported")
    translator = get_translator(src, dst)
    groups = group_sentences(cues)
    print(f"Translating {len(cues)} lines as {len(groups)} sentences into {dst}...", flush=True)
    out = [""] * len(cues)
    for n, idxs in enumerate(groups, 1):
        texts = [cues[i]["text"] for i in idxs]
        sentence = clean_for_translation(" ".join(texts))
        translated = translator.translate(sentence) if sentence else ""
        for i, part in zip(idxs, spread(translated, texts)):
            out[i] = part
        if n % 25 == 0 or n == len(groups):
            print(f"Translated {n} of {len(groups)} sentences", flush=True)
    return out


def get_cues(video_id, lang):
    key = f"{video_id}|{lang}"
    if key in translation_cache:
        return translation_cache[key]
    cues, original_lang = get_original(video_id)
    src = original_lang.split("-")[0]
    if lang == src:
        return cues
    translated = translate_cues(cues, src, lang)
    translation_cache[key] = [
        {"start": c["start"], "end": c["end"], "text": text}
        for c, text in zip(cues, translated)
    ]
    save_json(CACHE_FILE, translation_cache)
    print("Translation done and saved.", flush=True)
    return translation_cache[key]


def tidy_meaning(meaning, word, force_lower=False):
    meaning = meaning.strip()
    if meaning.endswith(".") and not word.endswith("."):
        meaning = meaning[:-1]
    if (word[:1].islower() or force_lower) and meaning[:1].isupper() and not meaning[:2].isupper():
        meaning = meaning[:1].lower() + meaning[1:]
    return meaning


def gloss(src, dst, word):
    if (src, dst) in broken_pairs:
        return None
    translator = get_translator(src, dst)
    lower = word.lower()
    tries = []
    if src in FRAMES:
        tries.append(("frame", FRAMES[src].format(word)))
        if lower != word:
            tries.append(("frame-lower", FRAMES[src].format(lower)))
    tries.append(("period", word + "."))
    if lower != word:
        tries.append(("plain-lower", lower))
    tries.append(("plain", word))
    for name, text in tries:
        out = translator.translate(text).strip()
        if name.startswith("frame"):
            out = PREFIX_RE.sub("", out)
        out = out.strip().strip(EDGE_CHARS).strip()
        print(f"define {src}->{dst} [{name}] {text!r} -> {out[:60]!r}", flush=True)
        if is_garbage(out):
            broken_pairs.add((src, dst))
            print(f"{src}->{dst} gives garbage, skipping word lookups for it.", flush=True)
            return None
        if not out or looks_broken(out):
            continue
        if out.lower() == lower:
            continue
        return tidy_meaning(out, word, src == "ko")
    return None


def analyze_korean(word):
    tokens = get_kiwi().tokenize(word)
    forms = [t.form for t in tokens]
    tags = [t.tag.split("-")[0] for t in tokens]
    print(f"kiwi {word!r}: {list(zip(forms, tags))}", flush=True)

    notes = []
    for form, tag in zip(forms, tags):
        if tag.startswith("J") and form in PARTICLES:
            notes.append(f"{form}: {PARTICLES[form]}")
        elif tag.startswith("E") and form in ENDINGS:
            notes.append(f"{form}: {ENDINGS[form]}")

    verbal_idx = None
    for i, tag in enumerate(tags):
        if tag in ("VV", "VA", "XSV", "XSA"):
            verbal_idx = i
            break

    if verbal_idx is not None:
        stem = forms[verbal_idx]
        if (
            tags[verbal_idx] in ("XSV", "XSA")
            and verbal_idx > 0
            and (tags[verbal_idx - 1] in NOUN_TAGS or tags[verbal_idx - 1] == "XR")
        ):
            stem = forms[verbal_idx - 1] + stem
        return {"lemma": stem + "다", "verbal": True, "notes": notes}

    lead = []
    for form, tag in zip(forms, tags):
        if tag in NOUN_TAGS:
            lead.append(form)
        elif lead:
            break
        elif tag in ("MAG", "MM", "IC", "MAJ"):
            lead = [form]
            break
    lemma = "".join(lead) or word
    return {"lemma": lemma, "verbal": False, "notes": notes}


def korean_meaning(word):
    try:
        info = analyze_korean(word)
    except Exception as e:
        print(f"Korean analysis unavailable: {type(e).__name__}", flush=True)
        return gloss("ko", "en", word)

    base = gloss("ko", "en", info["lemma"])
    if not base and info["lemma"] != word:
        base = gloss("ko", "en", word)

    parts = []
    if base:
        if info["verbal"] and " " not in base and not base.startswith("to "):
            base = "to " + base
        text = base
        if info["lemma"] != word:
            text += f" ({info['lemma']})"
        parts.append(text)
    if info["notes"]:
        parts.append("; ".join(info["notes"]))
    return " · ".join(parts) if parts else None


def original_line(video_id, cue):
    try:
        cues, _ = get_original(video_id)
        return clean_for_translation(cues[int(cue)]["text"])
    except Exception:
        return ""


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


@app.route("/api/define")
def define():
    raw = request.args.get("word", "")
    src = request.args.get("from", "en")
    dst = request.args.get("to", "en")
    video_id = request.args.get("videoId", "")
    cue = request.args.get("cue", "")
    word = raw.strip().strip(EDGE_CHARS).strip()
    if not word:
        return jsonify(error="No word there")
    if src == dst or src not in SUPPORTED_LANGS or dst not in SUPPORTED_LANGS:
        return jsonify(error="Language not supported")
    key = f"{src}|{dst}|{word.lower()}"
    try:
        meaning = define_cache.get(key, "")
        if not meaning:
            if src == "ko" and dst == "en":
                result = korean_meaning(word)
            else:
                result = gloss(src, dst, word)
            if result:
                define_cache[key] = result
                meaning = result
        line = original_line(video_id, cue) if video_id and cue != "" else ""
        if not meaning and not line:
            return jsonify(error="No clear meaning")
        return jsonify(original=word, meaning=meaning, line=line)
    except TranslateError as e:
        return jsonify(error=str(e))
    except Exception as e:
        return jsonify(
            error="Couldn't look that up.",
            debug=f"{type(e).__name__}: {e}",
        )


if __name__ == "__main__":
    threading.Thread(target=preload, daemon=True).start()
    app.run(port=8000)
