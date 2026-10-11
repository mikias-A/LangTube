# LangTube

A web app built mainly on JavaScript, Python/Flask and p5.js that takes a YouTube video and displays clickable captions alongside it. Clicking any word shows its translation and dictionary definition in your target language.

**Supported languages:** English, Spanish, Korean, Chinese (Simplified)

Everything runs on your own computer. Nothing is hosted online, and the server only listens on your own machine.

https://github.com/user-attachments/assets/5cda18e5-8f58-4679-a10c-1879f1252ce7


## What you need

- Windows with Python 3 (developed and tested on Python 3.14)
- A web browser and an internet connection
- Roughly 1 GB of storage for the language data

## Setup

```bash
git clone https://github.com/mikias-A/langtube.git
cd langtube
python -m pip install -r requirements.txt
```


## Run

```bash
python server.py
```

The first start downloads language packs and dictionaries (one time, a few hundred MB to about 1 GB). 
Wait until the terminal prints `Language packs ready.`, then open http://localhost:8000 in your browser.

## How to use

1. Paste a YouTube link and pick a language flag.
2. Translated captions appear next to the video. Videos in other languages work too: pick English to read them in English.
3. Click a word to pause the video and see its meaning.
   - Korean words are split into their parts, with explanations of particles and endings.
   - Chinese shows pinyin, definitions and a character breakdown.
4. Flip Captions switches between your language and English (from English it switches to Spanish).

The video needs captions. Translations are machine-generated, so expect mistakes, especially with slang.

## Stop

Press Ctrl+C in the terminal, then close the browser tab.

## Notes

- Works on desktop browsers. Phones and tablets aren't supported.
- The first translation of a video takes a little while. After that, the result is saved on your computer.

## Credits

- YouTube captions via youtube-transcript-api
- Translation: Argos Translate and Helsinki-NLP Opus-MT models (CTranslate2 conversions by michaelfeil and gaudi)
- Korean: Kiwi (kiwipiepy) and the Kengdic dictionary
- Chinese: the CC-CEDICT dictionary (CC BY-SA)

See each project for its license terms.
