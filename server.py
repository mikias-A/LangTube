import csv
import gzip
import json
import os
import re
import threading
import requests
from flask import Flask, request, jsonify, send_from_directory
from youtube_transcript_api import YouTubeTranscriptApi, NoTranscriptFound
import argostranslate.package
import argostranslate.settings
import argostranslate.translate

app = Flask(__name__, static_folder=".", static_url_path="")

SUPPORTED_LANGS = ("en", "es", "ko", "zh")
CACHE_FILE = "translation_cache_v3.json"
ORIGINAL_FILE = "original_cache_v2.json"
REPAIR_FILE = "pack_repairs_v3.json"
MAX_CHARS = 70
PAUSE_GAP = 1.0
SENTENCE_MAX = 240
EDGE_CHARS = ".,!?;:\"'()[]{}¿¡…—–-<>»«“”‘’*"
PRELOAD_PAIRS = [
    ("en", "es"),
    ("en", "ko"),
    ("es", "en"),
    ("ko", "en"),
    ("en", "zh"),
]
TEST_WORDS = {"en": "house", "es": "casa", "ko": "집"}
FRAMES = {"en": "Word: {}"}
PREFIX_RE = re.compile(r"^\s*(word|palabra|단어)s?\s*[:：]?\s*", re.IGNORECASE)
BAD_GLOSSES = {"about us", "tag"}

MARIAN_MODELS = {
    ("es", "en"): {
        "name": "Spanish",
        "repo": "michaelfeil/ct2fast-opus-mt-es-en",
        "dir": os.path.join("models", "opus-mt-es-en"),
        "prefix": None,
    },
    ("en", "zh"): {
        "name": "Chinese",
        "repo": "gaudi/opus-mt-en-zh-ctranslate2",
        "dir": os.path.join("models", "opus-mt-en-zh"),
        "prefix": ">>cmn_Hans<<",
    },
}

KENGDIC_URL = "https://raw.githubusercontent.com/garfieldnate/kengdic/master/kengdic.tsv"
KENGDIC_FILE = os.path.join("data", "kengdic.tsv")

CEDICT_URL = "https://www.mdbg.net/chinese/export/cedict/cedict_1_0_ts_utf-8_mdbg.txt.gz"
CEDICT_FILE = os.path.join("data", "cedict_ts.u8")
CEDICT_RE = re.compile(r"^(\S+)\s+(\S+)\s+\[([^\]]*)\]\s+/(.*)/\s*$")
ZH_MAX = 8
SKIP_DEF_STARTS = ("variant of", "old variant of", "surname ", "see ", "also written")

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

TONE_MARKS = {
    "a": "āáǎàa",
    "e": "ēéěèe",
    "i": "īíǐìi",
    "o": "ōóǒòo",
    "u": "ūúǔùu",
    "ü": "ǖǘǚǜü",
}

pack_lock = threading.Lock()
marian_lock = threading.Lock()
kiwi_lock = threading.Lock()
kdict_lock = threading.Lock()
zh_lock = threading.Lock()
marian_models = {}
kiwi_obj = None
kdict = None
kdict_failed = False
zh_dict = None
zh_reverse = None
zh_failed = False
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
    def __init__(self, folder, prefix=None):
        import ctranslate2
        import sentencepiece

        self.prefix = prefix
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
        tokens = (
            ([self.prefix] if self.prefix else [])
            + self.sp_src.encode(text, out_type=str)
            + ["</s>"]
        )
        results = self.translator.translate_batch(
            [tokens], beam_size=4, max_decoding_length=256
        )
        return self.sp_tgt.decode_pieces(results[0].hypotheses[0])


class PivotTranslation:
    def __init__(self, first, second):
        self.first = first
        self.second = second

    def translate(self, text):
        return self.second.translate(self.first.translate(text))


def get_marian(key):
    cfg = MARIAN_MODELS[key]
    with marian_lock:
        if key in marian_models:
            return marian_models[key]
        if not os.path.exists(os.path.join(cfg["dir"], "model.bin")):
            print(
                f"Downloading the {cfg['name']} model (first time only, may take a few minutes)...",
                flush=True,
            )
            try:
                from huggingface_hub import snapshot_download

                snapshot_download(repo_id=cfg["repo"], local_dir=cfg["dir"])
            except Exception as e:
                print(f"Download problem: {e}", flush=True)
                raise TranslateError(f"{cfg['name']} model missing")
        marian_models[key] = MarianTranslation(cfg["dir"], cfg["prefix"])
        return marian_models[key]


def get_kiwi():
    global kiwi_obj
    with kiwi_lock:
        if kiwi_obj is None:
            from kiwipiepy import Kiwi

            kiwi_obj = Kiwi()
        return kiwi_obj


def load_kengdic():
    global kdict, kdict_failed
    with kdict_lock:
        if kdict is not None:
            return kdict
        if kdict_failed:
            raise RuntimeError("dictionary unavailable")
        try:
            if not os.path.exists(KENGDIC_FILE):
                print("Downloading the Korean dictionary (first time only)...", flush=True)
                os.makedirs("data", exist_ok=True)
                res = requests.get(KENGDIC_URL, timeout=120)
                res.raise_for_status()
                with open(KENGDIC_FILE, "wb") as f:
                    f.write(res.content)
            with open(KENGDIC_FILE, "r", encoding="utf-8", errors="replace", newline="") as f:
                rows = list(csv.reader(f, delimiter="\t", quoting=csv.QUOTE_NONE))
            if not rows:
                raise RuntimeError("dictionary file is empty")
            names = [h.strip().lower() for h in rows[0]]
            if "surface" in names and "gloss" in names:
                si = names.index("surface")
                gi = names.index("gloss")
                data = rows[1:]
            else:
                si, gi = 1, 3
                data = rows
            entries = {}
            for row in data:
                if len(row) <= max(si, gi):
                    continue
                surface = row[si].strip()
                gloss_text = row[gi].strip()
                if not surface or not gloss_text or gloss_text.lower() in ("null", "none"):
                    continue
                entries.setdefault(surface, []).append(gloss_text)
            if not entries:
                raise RuntimeError("no entries could be read")
            kdict = entries
            return kdict
        except Exception:
            kdict_failed = True
            raise


def dict_meaning(candidates):
    entries = load_kengdic()
    for cand in candidates:
        glosses = entries.get(cand)
        if not glosses:
            continue
        senses = []
        seen = set()
        for g in glosses:
            for part in g.split(";"):
                part = part.strip()
                if not part or len(part) > 40 or part.lower() in seen:
                    continue
                seen.add(part.lower())
                senses.append(part)
            if len(senses) >= 4:
                break
        if senses:
            print(f"dictionary hit for {cand!r}: {senses[:4]}", flush=True)
            return "; ".join(senses[:4])
    return None


def load_cedict():
    global zh_dict, zh_failed
    with zh_lock:
        if zh_dict is not None:
            return zh_dict
        if zh_failed:
            raise RuntimeError("dictionary unavailable")
        try:
            if not os.path.exists(CEDICT_FILE):
                print("Downloading the Chinese dictionary (first time only)...", flush=True)
                os.makedirs("data", exist_ok=True)
                res = requests.get(CEDICT_URL, timeout=120)
                res.raise_for_status()
                data = res.content
                try:
                    data = gzip.decompress(data)
                except Exception:
                    pass
                with open(CEDICT_FILE, "wb") as f:
                    f.write(data)
            entries = {}
            with open(CEDICT_FILE, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    if line.startswith("#"):
                        continue
                    m = CEDICT_RE.match(line.strip())
                    if not m:
                        continue
                    trad, simp, pin, defs = m.groups()
                    meanings = [d.strip() for d in defs.split("/") if d.strip()]
                    entry = {"simp": simp, "trad": trad, "pinyin": pin, "defs": meanings}
                    for key in {simp, trad}:
                        entries.setdefault(key, []).append(entry)
            if not entries:
                raise RuntimeError("no entries could be read")
            zh_dict = entries
            return zh_dict
        except Exception:
            zh_failed = True
            raise


def get_cedict():
    try:
        return load_cedict()
    except Exception as e:
        print(f"Chinese dictionary problem: {type(e).__name__}: {e}", flush=True)
        raise TranslateError("Chinese dictionary missing")


def get_reverse():
    global zh_reverse
    entries = get_cedict()
    with zh_lock:
        if zh_reverse is not None:
            return zh_reverse
        rev = {}
        seen = set()
        for lst in entries.values():
            for e in lst:
                if id(e) in seen:
                    continue
                seen.add(id(e))
                if len(e["simp"]) > 4:
                    continue
                for d in e["defs"]:
                    key = d.lower().strip()
                    if not key or len(key) > 30 or key.startswith("cl:"):
                        continue
                    keys = {key}
                    if key.startswith("to "):
                        keys.add(key[3:])
                    for k in keys:
                        rev.setdefault(k, []).append(e)
        for k in rev:
            rev[k].sort(key=lambda e: len(e["simp"]))
        zh_reverse = rev
        return zh_reverse


def mark_syllable(syl):
    syl = syl.replace("u:", "ü").replace("U:", "Ü")
    m = re.match(r"^(.*?)([1-5])$", syl)
    if not m:
        return syl
    base, tone = m.group(1), int(m.group(2))
    if tone == 5:
        return base
    low = base.lower()
    idx = -1
    if "a" in low:
        idx = low.index("a")
    elif "e" in low:
        idx = low.index("e")
    elif "ou" in low:
        idx = low.index("o")
    else:
        for i in range(len(low) - 1, -1, -1):
            if low[i] in "aeiouü":
                idx = i
                break
    if idx < 0:
        return base
    mark = TONE_MARKS[low[idx]][tone - 1]
    if base[idx].isupper():
        mark = mark.upper()
    return base[:idx] + mark + base[idx + 1:]


def pinyin_marks(numbered):
    return " ".join(mark_syllable(s) for s in numbered.split())


def is_cjk(ch):
    return "\u3400" <= ch <= "\u9fff"


def segment_zh(text, entries):
    segs = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if is_cjk(ch):
            end = i + 1
            for size in range(min(ZH_MAX, n - i), 1, -1):
                chunk = text[i:i + size]
                if all(is_cjk(c) for c in chunk) and chunk in entries:
                    end = i + size
                    break
            segs.append((i, end))
            i = end
        elif ch.isalnum():
            j = i
            while j < n and text[j].isalnum() and not is_cjk(text[j]):
                j += 1
            segs.append((i, j))
            i = j
        elif ch.isspace():
            i += 1
        else:
            segs.append((i, i + 1))
            i += 1
    return segs


def short_def(d, limit=40):
    return d if len(d) <= limit else d[: limit - 1] + "…"


def useful_defs(entry):
    defs = [d for d in entry["defs"] if not d.startswith("CL:")]
    return defs or entry["defs"]


def plain_def(entry):
    defs = useful_defs(entry)
    for d in defs:
        if not d.lower().startswith(SKIP_DEF_STARTS):
            return d
    return defs[0] if defs else ""


def format_entry(entry, max_defs=3):
    defs = [short_def(d) for d in useful_defs(entry)[:max_defs]]
    return f"{pinyin_marks(entry['pinyin'])}: " + "; ".join(defs)


def chinese_meaning(text, pos, clicked):
    entries = get_cedict()
    text = text[:300]
    try:
        pos = int(pos)
    except ValueError:
        pos = -1
    if not text or pos < 0 or pos >= len(text):
        text, pos = clicked, 0
    seg = None
    for s, e in segment_zh(text, entries):
        if s <= pos < e:
            seg = (s, e)
            break
    if seg is None:
        return {"error": "No word there"}
    s, e = seg
    word = text[s:e]
    if not any(is_cjk(c) for c in word):
        return {"error": "Not a Chinese word"}
    cands = entries.get(word, [])
    meaning = " | ".join(format_entry(c) for c in cands[:2])
    extra_parts = []
    if len(word) >= 2:
        for ch in word[:4]:
            ce = entries.get(ch)
            if not ce:
                continue
            extra_parts.append(
                f"{ch} {pinyin_marks(ce[0]['pinyin'])}: {short_def(plain_def(ce[0]), 18)}"
            )
    print(f"chinese {word!r} ({s}-{e}): {meaning[:80]!r}", flush=True)
    return {
        "original": word,
        "meaning": meaning,
        "extra": " · ".join(extra_parts),
        "start": s,
        "end": e,
    }


def english_candidates(word):
    w = word.lower()
    out = [w]
    if w.endswith("ies") and len(w) > 4:
        out.append(w[:-3] + "y")
    if w.endswith("es") and len(w) > 3:
        out.append(w[:-2])
    if w.endswith("s") and len(w) > 3:
        out.append(w[:-1])
    if w.endswith("ing") and len(w) > 5:
        out.extend([w[:-3], w[:-3] + "e"])
    if w.endswith("ed") and len(w) > 4:
        out.extend([w[:-2], w[:-1]])
    seen = set()
    return [c for c in out if not (c in seen or seen.add(c))]


def english_to_chinese(word):
    rev = get_reverse()
    for cand in english_candidates(word):
        lst = rev.get(cand)
        if not lst:
            continue
        out = []
        seen = set()
        for e in lst:
            if e["simp"] in seen:
                continue
            seen.add(e["simp"])
            out.append(f"{e['simp']} {pinyin_marks(e['pinyin'])}")
            if len(out) >= 3:
                break
        if out:
            return "; ".join(out)
    return None


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
    if src != "en" and dst != "en" and src != dst:
        translators[key] = PivotTranslation(
            get_translator(src, "en"), get_translator("en", dst)
        )
        return translators[key]
    if key in MARIAN_MODELS:
        translators[key] = get_marian(key)
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
    if dst == "zh" and not re.search(r"[\u3400-\u9fff]", out):
        print("The answer has no Chinese characters in it.", flush=True)
        return False
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
            if (src, dst) in MARIAN_MODELS:
                broken_pairs.add((src, dst))
                print(
                    f"{src} -> {dst} model isn't working. Send me the lines above this one.",
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
    try:
        n = len(load_kengdic())
        print(f"Korean dictionary ready ({n} entries).", flush=True)
    except Exception as e:
        print(
            f"Korean dictionary not available ({type(e).__name__}: {e}). Word meanings will use the translator instead.",
            flush=True,
        )
    try:
        n = len(get_cedict())
        get_reverse()
        print(f"Chinese dictionary ready ({n} entries).", flush=True)
    except Exception as e:
        print(f"Chinese dictionary not available ({e}).", flush=True)
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


def split_units(text, zh):
    if zh:
        return re.findall(r"[A-Za-z0-9]+|[^\s]", text)
    return text.split()


def join_units(units, zh):
    if not zh:
        return " ".join(units)
    out = ""
    prev = ""
    for u in units:
        if (
            prev
            and prev[-1].isascii()
            and prev[-1].isalnum()
            and u[0].isascii()
            and u[0].isalnum()
        ):
            out += " "
        out += u
        prev = u
    return out


def spread(translated, texts, zh=False):
    n = len(texts)
    if n == 1:
        return [translated.strip()]
    units = split_units(translated, zh)
    total = sum(max(len(t), 1) for t in texts)
    parts = []
    used = 0
    running = 0
    for k, t in enumerate(texts):
        running += max(len(t), 1)
        if k == n - 1:
            end = len(units)
        else:
            end = round(len(units) * running / total)
        parts.append(join_units(units[used:end], zh))
        used = end
    return parts


def translate_cues(cues, src, dst):
    if dst not in SUPPORTED_LANGS:
        raise TranslateError("Language not supported")
    if dst == "zh" and ("en", "zh") in broken_pairs:
        raise TranslateError("Chinese model not working")
    translator = get_translator(src, dst)
    zh = dst == "zh"
    groups = group_sentences(cues)
    print(f"Translating {len(cues)} lines as {len(groups)} sentences into {dst}...", flush=True)
    out = [""] * len(cues)
    for n, idxs in enumerate(groups, 1):
        texts = [cues[i]["text"] for i in idxs]
        sentence = clean_for_translation(" ".join(texts))
        translated = translator.translate(sentence) if sentence else ""
        for i, part in zip(idxs, spread(translated, texts, zh)):
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
        if src == "ko" and out.lower() in BAD_GLOSSES:
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
        info = {"lemma": word, "verbal": False, "notes": []}

    candidates = [info["lemma"]]
    if info["verbal"]:
        candidates.append(info["lemma"][:-1])
    if word not in candidates:
        candidates.append(word)

    base = None
    try:
        base = dict_meaning(candidates)
    except Exception as e:
        print(f"Korean dictionary unavailable: {type(e).__name__}", flush=True)

    if not base:
        base = gloss("ko", "en", info["lemma"])
        if not base and info["lemma"] != word:
            base = gloss("ko", "en", word)
        if base and info["verbal"] and " " not in base and not base.startswith("to "):
            base = "to " + base

    parts = []
    if base:
        text = base
        if info["lemma"] != word:
            text += f" ({info['lemma']})"
        parts.append(text)
    if info["notes"]:
        parts.append("; ".join(info["notes"]))
    return " · ".join(parts) if parts else None


def original_line(video_id, cue, shown_lang):
    try:
        cues, original_lang = get_original(video_id)
        code = original_lang.split("-")[0]
        if code == shown_lang:
            return "", code
        return clean_for_translation(cues[int(cue)]["text"]), code
    except Exception:
        return "", ""


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
    try:
        line, line_lang = ("", "")
        if video_id and cue != "":
            line, line_lang = original_line(video_id, cue, src)

        if src == "zh" and dst == "en":
            text = request.args.get("text", "")
            pos = request.args.get("pos", "-1")
            info = chinese_meaning(text, pos, word)
            if info.get("error"):
                return jsonify(error=info["error"])
            return jsonify(
                original=info["original"],
                meaning=info["meaning"],
                extra=info["extra"],
                start=info["start"],
                end=info["end"],
                line=line,
                line_lang=line_lang,
            )

        if dst == "zh":
            meaning = english_to_chinese(word)
            if not meaning and not line:
                return jsonify(error="No clear meaning")
            return jsonify(
                original=word, meaning=meaning or "", line=line, line_lang=line_lang
            )

        key = f"{src}|{dst}|{word.lower()}"
        meaning = define_cache.get(key, "")
        if not meaning:
            if src == "ko" and dst == "en":
                result = korean_meaning(word)
            else:
                result = gloss(src, dst, word)
            if result:
                define_cache[key] = result
                meaning = result
        if not meaning and not line:
            return jsonify(error="No clear meaning")
        return jsonify(original=word, meaning=meaning, line=line, line_lang=line_lang)
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
