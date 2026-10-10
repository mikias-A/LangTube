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
