export default async function handler(req, res) {
  const { videoId } = req.query;
  res.setHeader("Cache-Control", "no-store");

  if (!videoId) {
    return res.status(400).json({ error: "Missing videoId" });
  }

  try {
    const pageRes = await fetch(`https://www.youtube.com/watch?v=${videoId}`, {
      headers: {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
      }
    });
    const html = await pageRes.text();

    const match = html.match(/"captionTracks":(\[.*?\])/);
    if (!match) {
      return res.status(404).json({ error: "No captions found for this video." });
    }

    const tracks = JSON.parse(match[1]);
    if (!tracks.length) {
      return res.status(404).json({ error: "No captions found for this video." });
    }

    const track = tracks.find(t => t.languageCode === "en") || tracks[0];
    const baseUrl = track.baseUrl.replace(/\\u0026/g, "&");

    const capRes = await fetch(baseUrl);
    const capXML = await capRes.text();

    const cues = [];
    const regex = /<text start="([\d.]+)" dur="([\d.]+)"[^>]*>([^<]*)<\/text>/g;
    let m;
    while ((m = regex.exec(capXML)) !== null) {
      const clean = m[3]
        .replace(/&#39;/g, "'")
        .replace(/&amp;/g, "&")
        .replace(/&quot;/g, '"');
      cues.push({ start: parseFloat(m[1]), end: parseFloat(m[1]) + parseFloat(m[2]), text: clean });
    }

    res.status(200).json({ cues });
  } catch (err) {
    res.status(500).json({ error: "Failed to fetch captions." });
  }
}
