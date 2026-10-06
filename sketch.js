let spFlag, krFlag, PaperBG, logo;
//image and background rect anim
let spainBox = { x: 267, y: 480, w: 273, h: 180, r: 30, hover: 0 };
let koreaBox = { x: 740, y: 480, w: 273, h: 180, r: 30, hover: 0 };
const pad = 8;

let lang;
let screen = "home";

let videoURL = "";
let inputActive = false;
const urlBox = { x: 40, y: 370, w: 1200, h: 80 };

let newVideoURL = "";
let inputActive2 = false;
const urlBox2 = { x: 32, y: 55, w: 610, h: 42 };

let spainBox2 = { x: 665, y: 53, w: 60, h: 42, r: 10, hover: 0 };
let koreaBox2 = { x: 745, y: 53, w: 60, h: 42, r: 10, hover: 0 };

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

function extractVideoID(url) {
  let regExp = /(?:youtube\.com.*(?:\?|&)v=|youtu\.be\/)([a-zA-Z0-9_-]{11})/;
  let match = url.match(regExp);
  return match ? match[1] : null;
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

function getActiveCueIndex(currentTime) {
  for (let i = captionCues.length - 1; i >= 0; i--) {
    if (currentTime >= captionCues[i].start) return i;
  }
  return -1;
}

function drawCaptions(panelX, panelY, panelW, panelH) {
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
      text(captionCues[i].text, panelX + 80, y, panelW - 104);
    }
  }

  drawingContext.restore();
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

    let spainHit = mouseX > spainBox.x - pad && mouseX < spainBox.x + spainBox.w + pad &&
                   mouseY > spainBox.y - pad && mouseY < spainBox.y + spainBox.h + pad;
    let koreaHit = mouseX > koreaBox.x - pad && mouseX < koreaBox.x + koreaBox.w + pad &&
                   mouseY > koreaBox.y - pad && mouseY < koreaBox.y + koreaBox.h + pad;

    if (videoURL.trim().length > 0) {
      if (spainHit) { targetLang = "es"; screen = "main"; loadYouTubeVideo(videoURL); }
      else if (koreaHit) { targetLang = "ko"; screen = "main"; loadYouTubeVideo(videoURL); }
    }
  }

  if (screen === "main") {
    inputActive2 = isInsideUrlBox2();

    let spainHit2 = mouseX > spainBox2.x - pad && mouseX < spainBox2.x + spainBox2.w + pad &&
                    mouseY > spainBox2.y - pad && mouseY < spainBox2.y + spainBox2.h + pad;
    let koreaHit2 = mouseX > koreaBox2.x - pad && mouseX < koreaBox2.x + koreaBox2.w + pad &&
                    mouseY > koreaBox2.y - pad && mouseY < koreaBox2.y + koreaBox2.h + pad;

    if (newVideoURL.trim().length > 0) {
      if (spainHit2) { targetLang = "es"; videoURL = newVideoURL; newVideoURL = ""; loadYouTubeVideo(videoURL); }
      else if (koreaHit2) { targetLang = "ko"; videoURL = newVideoURL; newVideoURL = ""; loadYouTubeVideo(videoURL); }
    } else if (currentVideoId) {
      if (spainHit2) { targetLang = "es"; captionsInTarget = true; fetchTranscript(currentVideoId, targetLang); }
      else if (koreaHit2) { targetLang = "ko"; captionsInTarget = true; fetchTranscript(currentVideoId, targetLang); }
    }

    let pillHit = mouseX > captionPill.x && mouseX < captionPill.x + captionPill.w &&
                  mouseY > captionPill.y && mouseY < captionPill.y + captionPill.h;
    if (pillHit && currentVideoId) {
      captionsInTarget = !captionsInTarget;
      fetchTranscript(currentVideoId, captionsInTarget ? targetLang : "en");
    }
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

  drawFlagButton(spFlag, spainBox);
  drawFlagButton(krFlag, koreaBox);
}

function drawMainScreen() {
  image(PaperBG, 0, 0, width, height);
  noStroke();
  fill(0);
image(logo, 35, -40, 256, 144);
  
  // small flag icons, top-right — reusing your existing rounded-image helper
  drawFlagButton(spFlag, spainBox2);
  drawFlagButton(krFlag, koreaBox2);

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
}
