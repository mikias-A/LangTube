let spFlag, krFlag;
//image and background rect anim
let spainBox = { x: 267, y: 480, w: 273, h: 180, r: 30, hover: 0 };
let koreaBox = { x: 740, y: 480, w: 273, h: 180, r: 30, hover: 0 };
const pad = 8;

let screen = "default";

function preload() {
  spFlag = loadImage("spain-flag.png");
  krFlag = loadImage("south-korea-flag.png");
}
async function setup() {
  createCanvas(1280, 720);
  spFlag = await loadImage("spain-flag.png");
  krFlag = await loadImage("south-korea-flag.png");
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
  fill("#804CE0");
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
function mousePressed() {
  if (
    mouseX > 35 &&
    mouseX < 35 + textWidth("LangTube") &&
    mouseY > 25 &&
    mouseY < 55
  ) {
    screen = "home";
  }
}

function draw() {
  background("#D493FF");

  //logo top left
  stroke(0);
  strokeWeight(1);
  fill(0);
  textFont("Courier New", 27);
  textAlign(LEFT, BASELINE);
  text("LangTube", 35, 50);
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

  drawFlagButton(spFlag, spainBox);
  drawFlagButton(krFlag, koreaBox);
}
