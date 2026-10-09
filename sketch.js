let spFlag, krFlag, enFlag, chFlag, PaperBG, logo;
//image and background rect anim
let englishBox = { x: 40, y: 480, w: 240, h: 160, r: 30, hover: 0 };
let spainBox = { x: 360, y: 480, w: 240, h: 160, r: 30, hover: 0 };
let koreaBox = { x: 680, y: 480, w: 240, h: 160, r: 30, hover: 0 };
let chinaBox = { x: 1000, y: 480, w: 240, h: 160, r: 30, hover: 0 };
const pad = 8;

let lang;
let screen = "home";

let videoURL = "";
let inputActive = false;
const urlBox = { x: 40, y: 370, w: 1200, h: 80 };

let newVideoURL = "";
let inputActive2 = false;
const urlBox2 = { x: 32, y: 55, w: 610, h: 42 };

let englishBox2 = { x: 665, y: 53, w: 60, h: 42, r: 10, hover: 0 };
let spainBox2 = { x: 745, y: 53, w: 60, h: 42, r: 10, hover: 0 };
let koreaBox2 = { x: 825, y: 53, w: 60, h: 42, r: 10, hover: 0 };
let chinaBox2 = { x: 905, y: 53, w: 60, h: 42, r: 10, hover: 0 };

let backspaceHeld = false;
let backspaceHoldStart = 0;
let lastBackspaceTime = 0;
const backspaceInitialDelay = 400;
const backspaceRepeatRate = 50;

let ytPlayer = null;
let ytReady = false;
let pendingVideoId = null;

let captionCues = [];
let captionsLoading = false;
let captionsError = null;
let scrollOffset = 0;

let targetLang = "es";
let captionsInTarget = true;
let currentVideoId = null;
let captionRequestId = 0;
const captionPill = { x: 841, y: 663, w: 384, h: 39 };

let popup = null;
let wordBoxes = [];
let cueLayouts = {};
const capPanel = { x: 841, y: 130, w: 384, h: 516 };
const capRowH = 70;
const capLineH = 20;

function extractVideoID(url) {
  let regExp = /(?:youtube\.com.*(?:\?|&)v=|youtu\.be\/)([a-zA-Z0-9_-]{11})/;
  let match = url.match(regExp);
  return match ? match[1] : null;
}

function partnerLang(l) {
  return l === "en" ? "es" : "en";
}

function hitBox(box) {
  return mouseX > box.x - pad && mouseX < box.x + box.w + pad &&
         mouseY > box.y - pad && mouseY < box.y + box.h + pad;
}

function homeLangHit() {
  if (hitBox(englishBox)) return "en";
  if (hitBox(spainBox)) return "es";
  if (hitBox(koreaBox)) return "ko";
  if (hitBox(chinaBox)) return "zh";
  return null;
}

function mainLangHit() {
  if (hitBox(englishBox2)) return "en";
  if (hitBox(spainBox2)) return "es";
  if (hitBox(koreaBox2)) return "ko";
  if (hitBox(chinaBox2)) return "zh";
  return null;
}

window.onYouTubeIframeAPIReady = function () {
  console.log("YouTube API ready!");
  ytReady = true;
  if (pendingVideoId) {
    createOrLoadPlayer(pendingVideoId);
    pendingVideoId = null;
  }
};

function createOrLoadPlayer(videoId) {
  currentVideoId = videoId;
  captionsInTarget = true;
  if (!ytPlayer) {
    ytPlayer = new YT.Player("videoPlayer", {
      videoId: videoId,
      width: "789",
      height: "445",
    });
  } else {
    ytPlayer.loadVideoById(videoId);
  }
  fetchTranscript(videoId, targetLang);
}

function loadYouTubeVideo(url) {
  let id = extractVideoID(url);
  if (!id) {
    console.log("Couldn't find a valid YouTube video ID in that URL.");
    return;
  }
  if (!ytReady) {
    pendingVideoId = id;
  } else {
    createOrLoadPlayer(id);
  }
}

async function fetchTranscript(videoId, lang) {
  const myRequest = ++captionRequestId;
  captionCues = [];
  captionsError = null;
  captionsLoading = true;
  popup = null;
  cueLayouts = {};

  if (lang === "zh") {
    captionsError = "Chinese coming soon";
    captionsLoading = false;
    return;
  }

  try {
    let res = await fetch(`/api/transcript?videoId=${videoId}&lang=${lang}`);
    let data = await res.json();
    if (myRequest !== captionRequestId) return;

    if (data.error) {
      captionsError = data.error;
    } else {
      captionCues = data.cues;
    }
    captionsLoading = false;
  } catch (err) {
    if (myRequest !== captionRequestId) return;
    console.log("Caption fetch failed:", err);
    captionsError = "Couldn't load captions.";
    captionsLoading = false;
  }
}

async function lookUpWord(p) {
  const from = captionsInTarget ? targetLang : partnerLang(targetLang);
  const to = from === "en" ? (targetLang === "en" ? "es" : targetLang) : "en";
  let url = `/api/define?word=${encodeURIComponent(p.word)}&from=${from}&to=${to}`;
  if (currentVideoId) {
    url += `&videoId=${currentVideoId}&cue=${p.cueIndex}`;
  }
  try {
    let res = await fetch(url);
    let data = await res.json();
    if (popup !== p) return;
    if (data.error) {
      p.error = data.error;
    } else {
      p.original = data.original;
      p.meaning = data.meaning || "";
      p.line = data.line || "";
      p.lineLang = data.line_lang || "en";
    }
    p.loading = false;
  } catch (err) {
    if (popup !== p) return;
    p.error = "Couldn't look that up.";
    p.loading = false;
  }
}

function getActiveCueIndex(currentTime) {
  for (let i = captionCues.length - 1; i >= 0; i--) {
    if (currentTime >= captionCues[i].start) return i;
  }
  return -1;
}

function getLayout(i) {
  if (cueLayouts[i]) return cueLayouts[i];
  textFont("Courier New", 16);
  const maxW = capPanel.w - 104;
  let spaceW = textWidth("a a") - textWidth("aa");
  if (!(spaceW > 1)) spaceW = 9.6;
  let words = String(captionCues[i].text).split(/\s+/).filter(w => w.length > 0);
  let items = [];
  let x = 0;
  let line = 0;
  for (let w of words) {
    let ww = textWidth(w);
    if (x > 0 && x + ww > maxW) {
      line++;
      x = 0;
    }
    items.push({ text: w, x: x, line: line, w: ww });
    x += ww + spaceW;
  }
  cueLayouts[i] = { items: items, lines: line + 1 };
  return cueLayouts[i];
}

function wrapText(str, maxW) {
  let words = str.split(" ");
  let lines = [];
  let cur = "";
  for (let w of words) {
    let test = cur === "" ? w : cur + " " + w;
    if (cur !== "" && textWidth(test) > maxW) {
      lines.push(cur);
      cur = w;
    } else {
      cur = test;
    }
  }
  if (cur !== "") lines.push(cur);
  return lines;
}

function drawCaptions(panelX, panelY, panelW, panelH) {
  wordBoxes = [];
  drawingContext.save();
  drawingContext.beginPath();
  drawingContext.rect(panelX, panelY, panelW, panelH);
  drawingContext.clip();

  if (captionsLoading) {
    fill(0);
    textFont("Courier New", 16);
    textAlign(LEFT, TOP);
    text("Loading captions...", panelX + 24, panelY + 24);
  } else if (captionsError) {
    fill(0);
    textFont("Courier New", 16);
    textAlign(LEFT, TOP);
    text(captionsError, panelX + 24, panelY + 24);
  } else if (captionCues.length > 0 && ytPlayer && ytPlayer.getCurrentTime) {
    let currentTime = ytPlayer.getCurrentTime();
    let activeIndex = getActiveCueIndex(currentTime);

    let lineHeight = 70;
    let targetScroll = activeIndex * lineHeight;
    scrollOffset = lerp(scrollOffset, targetScroll, 0.1);

    textFont("Courier New", 16);
    textAlign(LEFT, TOP);

    for (let i = 0; i < captionCues.length; i++) {
      let y = panelY + 40 + (i * lineHeight) - scrollOffset;
      if (y < panelY - lineHeight || y > panelY + panelH) continue;

      if (i === activeIndex) {
        noStroke();
        fill(43, 251, 236, 80);
        rect(panelX + 10, y - 5, panelW - 20, lineHeight - 10, 8);
      }

      noStroke();
      fill(0);
      let timeLabel = formatTime(captionCues[i].start);
      text(timeLabel, panelX + 24, y);

      let layout = getLayout(i);
      let textLeft = panelX + 80;
      for (let k = 0; k < layout.items.length; k++) {
        let it = layout.items[k];
        let wx = textLeft + it.x;
        let wy = y + it.line * capLineH;
        if (popup && popup.cueIndex === i && popup.wordIndex === k) {
          noStroke();
          fill(43, 251, 236, 170);
          rect(wx - 3, wy - 1, it.w + 6, capLineH, 5);
          fill(0);
        }
        text(it.text, wx, wy);
        wordBoxes.push({
          x: wx,
          y: wy,
          w: it.w,
          cueIndex: i,
          wordIndex: k,
          text: it.text,
          relX: it.x,
          relY: it.line * capLineH,
        });
      }
    }
  }

  drawingContext.restore();
}

function drawPopup() {
  if (!popup || captionCues.length === 0) return;

  if (ytPlayer && ytPlayer.getPlayerState && ytPlayer.getPlayerState() === 1 &&
      millis() - popup.openedAt > 800) {
    popup = null;
    return;
  }

  let rowY = capPanel.y + 40 + popup.cueIndex * capRowH - scrollOffset;
  let wordTop = rowY + popup.relY;
  let wordBottom = wordTop + capLineH;
  if (wordBottom < capPanel.y || wordTop > capPanel.y + capPanel.h) {
    popup = null;
    return;
  }
  let wordCx = capPanel.x + 80 + popup.relX + popup.w / 2;

  let head = popup.original || popup.word;
  let meaningText;
  let meaningColor;
  let lineText = "";
  if (popup.loading) {
    meaningText = "Looking up...";
    meaningColor = 120;
  } else if (popup.error) {
    meaningText = popup.error;
    meaningColor = 120;
  } else {
    if (popup.meaning) {
      meaningText = popup.meaning;
      meaningColor = 0;
    } else {
      meaningText = "No word meaning";
      meaningColor = 120;
    }
    lineText = popup.line ? (popup.lineLang || "en").toUpperCase() + ": " + popup.line : "";
  }

  push();
  rectMode(CORNER);
  textAlign(LEFT, TOP);
  textFont("Courier New", 18);
  textStyle(BOLD);
  let headW = textWidth(head);
  textStyle(NORMAL);
  textFont("Courier New", 16);
  let meaningLines = wrapText(meaningText, 260);
  let widest = headW;
  for (let l of meaningLines) widest = max(widest, textWidth(l));
  textFont("Courier New", 14);
  let contextLines = lineText ? wrapText(lineText, 260) : [];
  for (let l of contextLines) widest = max(widest, textWidth(l));
  let boxW = constrain(widest + 32, 140, 300);
  let contextH = contextLines.length > 0 ? 6 + contextLines.length * 18 : 0;
  let boxH = 12 + 24 + meaningLines.length * capLineH + contextH + 12;

  let boxX = constrain(wordCx - boxW / 2, capPanel.x + 8, capPanel.x + capPanel.w - 8 - boxW);
  let below = wordBottom + 12 + boxH <= capPanel.y + capPanel.h;
  let boxY = below ? wordBottom + 12 : wordTop - 12 - boxH;

  let tipY = below ? wordBottom + 2 : wordTop - 2;
  let baseY = below ? boxY + 2 : boxY + boxH - 2;
  let baseX = constrain(wordCx, boxX + 20, boxX + boxW - 20);
  noStroke();
  fill("#2bfbec");
  triangle(wordCx, tipY, baseX - 9, baseY, baseX + 9, baseY);

  fill(255);
  stroke("#2bfbec");
  strokeWeight(3);
  rect(boxX, boxY, boxW, boxH, 16);

  noStroke();
  fill(0);
  textFont("Courier New", 18);
  textStyle(BOLD);
  text(head, boxX + 16, boxY + 12);
  textStyle(NORMAL);
  textFont("Courier New", 16);
  fill(meaningColor);
  let textY = boxY + 12 + 24;
  for (let n = 0; n < meaningLines.length; n++) {
    text(meaningLines[n], boxX + 16, textY + n * capLineH);
  }
  if (contextLines.length > 0) {
    textFont("Courier New", 14);
    fill(110);
    let contextY = textY + meaningLines.length * capLineH + 6;
    for (let n = 0; n < contextLines.length; n++) {
      text(contextLines[n], boxX + 16, contextY + n * 18);
    }
  }
  pop();

  popup.rect = { x: boxX, y: boxY, w: boxW, h: boxH };
}

function handleCaptionClick() {
  if (popup && popup.rect &&
      mouseX > popup.rect.x && mouseX < popup.rect.x + popup.rect.w &&
      mouseY > popup.rect.y && mouseY < popup.rect.y + popup.rect.h) {
    return;
  }

  let hit = null;
  if (mouseX > capPanel.x && mouseX < capPanel.x + capPanel.w &&
      mouseY > capPanel.y && mouseY < capPanel.y + capPanel.h) {
    for (let b of wordBoxes) {
      if (mouseX >= b.x - 3 && mouseX <= b.x + b.w + 3 &&
          mouseY >= b.y && mouseY <= b.y + capLineH) {
        hit = b;
        break;
      }
    }
  }

  if (!hit) {
    popup = null;
    return;
  }

  if (ytPlayer && ytPlayer.pauseVideo) ytPlayer.pauseVideo();

  popup = {
    cueIndex: hit.cueIndex,
    wordIndex: hit.wordIndex,
    word: hit.text,
    relX: hit.relX,
    relY: hit.relY,
    w: hit.w,
    original: null,
    meaning: null,
    line: "",
    lineLang: "en",
    error: null,
    loading: true,
    openedAt: millis(),
    rect: null,
  };
  lookUpWord(popup);
}

function formatTime(seconds) {
  let m = Math.floor(seconds / 60);
  let s = Math.floor(seconds % 60);
  return m + ":" + (s < 10 ? "0" : "") + s;
}

async function setup() {
  createCanvas(1280, 720);
  spFlag = await loadImage("spain-flag.png");
  krFlag = await loadImage("south-korea-flag.png");
  enFlag = await loadImage("english.jpg");
  chFlag = await loadImage("china.jpg");
  PaperBG = await loadImage("PaperBG.jpg");
  logo = await loadImage("logotube.png");

   let introVideo = document.getElementById("introVideo");
  introVideo.addEventListener("ended", () => {
    introVideo.style.display = "none";
  });

  let overlay = document.getElementById("startOverlay");
  overlay.addEventListener("click", () => {
    overlay.style.display = "none";
    introVideo.play();
  });

  document.addEventListener("paste", (e) => {
    let pastedText = (e.clipboardData || window.clipboardData).getData("text");
    if (screen === "home" && inputActive) {
      videoURL += pastedText;
    } else if (screen === "main" && inputActive2) {
      newVideoURL += pastedText;
    }
    e.preventDefault();
  });
}

function drawRoundedImage(img, x, y, w, h, r) {
  drawingContext.save();
  drawingContext.beginPath();
  drawingContext.roundRect(x, y, w, h, r);
  drawingContext.clip();
  image(img, x, y, w, h);
  drawingContext.restore();
}

function drawFlagButton(img, box) {
  let hovering =
    mouseX > box.x - pad &&
    mouseX < box.x + box.w + pad &&
    mouseY > box.y - pad &&
    mouseY < box.y + box.h + pad;
  box.hover = lerp(box.hover, hovering ? 1 : 0, 0.12);

  noStroke();
  fill("#2bfbec");
  drawingContext.beginPath();
  drawingContext.roundRect(
    box.x - pad,
    box.y - pad,
    box.w + pad * 2,
    (box.h + pad * 2) * box.hover,
    box.r + pad
  );
  drawingContext.fill();

  drawRoundedImage(img, box.x, box.y, box.w, box.h, box.r);
}

function isInsideUrlBox() {
  return mouseX > urlBox.x && mouseX < urlBox.x + urlBox.w &&
         mouseY > urlBox.y && mouseY < urlBox.y + urlBox.h;
}

function isInsideUrlBox2() {
  return mouseX > urlBox2.x && mouseX < urlBox2.x + urlBox2.w &&
         mouseY > urlBox2.y && mouseY < urlBox2.y + urlBox2.h;
}

function mousePressed() {
  if (
    mouseX > 35 &&
    mouseX < 35 + 160 &&
    mouseY > 25 &&
    mouseY < 55
  ) 
  {
    screen = "home";
  }

    if (screen === "home") {
    inputActive = isInsideUrlBox();

    let hitLang = homeLangHit();
    if (videoURL.trim().length > 0 && hitLang) {
      targetLang = hitLang;
      screen = "main";
      loadYouTubeVideo(videoURL);
    }
  }

  if (screen === "main") {
    inputActive2 = isInsideUrlBox2();

    let hitLang2 = mainLangHit();
    if (newVideoURL.trim().length > 0) {
      if (hitLang2) {
        targetLang = hitLang2;
        videoURL = newVideoURL;
        newVideoURL = "";
        loadYouTubeVideo(videoURL);
      }
    } else if (currentVideoId && hitLang2) {
      targetLang = hitLang2;
      captionsInTarget = true;
      fetchTranscript(currentVideoId, targetLang);
    }

    let pillHit = mouseX > captionPill.x && mouseX < captionPill.x + captionPill.w &&
                  mouseY > captionPill.y && mouseY < captionPill.y + captionPill.h;
    if (pillHit && currentVideoId) {
      captionsInTarget = !captionsInTarget;
      fetchTranscript(currentVideoId, captionsInTarget ? targetLang : partnerLang(targetLang));
    }

    handleCaptionClick();
  }
}

function keyTyped() {
  if (screen === "home" && inputActive) {
    videoURL += key;
  } else if (screen === "main" && inputActive2) {
    newVideoURL += key;
  }
}

function keyPressed() {
  if (screen === "home" && inputActive && key === "Backspace") {
    videoURL = videoURL.slice(0, -1);
    backspaceHeld = true;
    backspaceHoldStart = millis();
    lastBackspaceTime = millis();
    return false;
  }
  if (screen === "main" && inputActive2 && key === "Backspace") {
    newVideoURL = newVideoURL.slice(0, -1);
    backspaceHeld = true;
    backspaceHoldStart = millis();
    lastBackspaceTime = millis();
    return false;
  }
}

function keyReleased() {
  if (key === "Backspace") {
    backspaceHeld = false;
  }
}

function handleBackspaceHold() {
  if (!backspaceHeld) return;
  let now = millis();
  if (now - backspaceHoldStart > backspaceInitialDelay &&
      now - lastBackspaceTime > backspaceRepeatRate) {
    if (screen === "home" && inputActive) {
      videoURL = videoURL.slice(0, -1);
      lastBackspaceTime = now;
    } else if (screen === "main" && inputActive2) {
      newVideoURL = newVideoURL.slice(0, -1);
      lastBackspaceTime = now;
    }
  }
}

function draw(){
  let playerDiv = document.getElementById("videoPlayer");
  if (playerDiv) {
    playerDiv.style.display = (screen === "main" && ytPlayer) ? "block" : "none";
  }

  handleBackspaceHold();
    if (screen === "home") {
    drawHomeScreen();
  } else if (screen === "main") {
    drawMainScreen();
  }
}

function drawHomeScreen() {
  image(PaperBG, 0, 0, width, height);

  //logo top left
  stroke(0);
  strokeWeight(1);
  fill(0);
image(logo, 35, -40, 256, 144);
  //the lines beneath it
  line(38, 70, 1242, 70);
  line(38, 110, 1242, 110);

  //center Welcome
  stroke(0);
  strokeWeight(3);
  textFont("Courier New", 50);
  textAlign(CENTER, CENTER);
  text("Welcome to LangTube!", 1280 / 2, 720 / 2 - 100);
  //enter url and its box
  textFont("Courier New", 38);
  textAlign(CENTER, CENTER);
  text("Enter URL and pick your language to start.", 1280 / 2, 720 / 2 - 40);
  fill(255);
  rectMode(CENTER);
  rect(1280 / 2, 720 / 2 + 50, 1200, 80, 120);

  noStroke();
  fill(videoURL.length > 0 ? 0 : 150);
  textFont("Courier New", 24);
  textAlign(LEFT, CENTER);
  let displayText = videoURL.length > 0 ? videoURL : "Paste a YouTube URL here...";
  text(displayText, urlBox.x + 30, urlBox.y + urlBox.h / 2);

  if (inputActive && frameCount % 60 < 30) {
    let cursorX = urlBox.x + 30 + textWidth(videoURL);
    stroke(0);
    strokeWeight(2);
    line(cursorX + 4, urlBox.y + 15, cursorX + 4, urlBox.y + urlBox.h - 15);
  }

  drawFlagButton(enFlag, englishBox);
  drawFlagButton(spFlag, spainBox);
  drawFlagButton(krFlag, koreaBox);
  drawFlagButton(chFlag, chinaBox);
}

function drawMainScreen() {
  image(PaperBG, 0, 0, width, height);
  noStroke();
  fill(0);
image(logo, 35, -40, 256, 144);
  
  // small flag icons, top-right — reusing your existing rounded-image helper
  drawFlagButton(enFlag, englishBox2);
  drawFlagButton(spFlag, spainBox2);
  drawFlagButton(krFlag, koreaBox2);
  drawFlagButton(chFlag, chinaBox2);

  // weather bubble — replaces the old plain weather text, same pill style as the title bubble
  noStroke();
  fill(255);
  if (inputActive2) {
    stroke("#2bfbec");
    strokeWeight(3);
  } else {
    stroke(0);
    strokeWeight(2);
  }
  rect(32, 55, 610, 42, 21);
  noStroke();
  fill(newVideoURL.length > 0 ? 0 : 150);
  textFont("Courier New", 18);
  textAlign(LEFT, CENTER);
  let displayText2 = newVideoURL.length > 0 ? newVideoURL : "Paste a new URL...";
  text(displayText2, urlBox2.x + 20, urlBox2.y + urlBox2.h / 2);

  if (inputActive2 && frameCount % 60 < 30) {
    let cursorX2 = urlBox2.x + 20 + textWidth(newVideoURL);
    stroke(0);
    strokeWeight(2);
    line(cursorX2 + 4, urlBox2.y + 8, cursorX2 + 4, urlBox2.y + urlBox2.h - 8);
  }


  // divider line under the header
  stroke(0);
  strokeWeight(2);
  line(32, 110, 1242, 110);

  // video title bubble
  noStroke();
  fill(255);
  stroke(0);
  strokeWeight(0);
  rect(32, 133, 790, 42, 21);
  noStroke();
  fill(0);
  textFont("Courier New", 22);
  textAlign(LEFT, CENTER);

  // video box (placeholder rectangle — real video element comes in Weekend 2)
  fill(20);
  noStroke();
  rectMode(CORNER);
  rect(31, 199, 789, 445, 12);

  // uploader bar
  fill(255);
  stroke(0);
  strokeWeight(0);
  rect(32, 663, 788, 39, 19);
  noStroke();
  fill(0);
  textFont("Courier New", 18);
  textAlign(LEFT, CENTER);

  // captions panel (big rounded rect on the right)
  fill(255);
  stroke(0);
  strokeWeight(0);
  rect(841, 130, 384, 516, 24);

  drawCaptions(841, 130, 384, 516);

   // captions language pill, bottom of the panel
  fill(255);
  stroke(0);
  strokeWeight(0);
  rect(841, 663, 384, 39, 19);
  noStroke();
  fill(0);
  textFont("Courier New", 15);
  textAlign(CENTER, CENTER);
  text("Flip Captions", captionPill.x + captionPill.w / 2, captionPill.y + captionPill.h / 2);

  drawPopup();
}
