export default async function handler(req, res) {
  const { videoId } = req.query;
  res.setHeader("Cache-Control", "no-store");

  if (!videoId) {
    return res.status(400).json({ error: "Missing videoId" });
  }

  try {
    const playerRes = await fetch(
      "https://www.youtube.com/youtubei/v1/player?key=AIzaSyAO_FJ2SlqU8Q4STEHLGCilw_Y9_11qcW8",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          videoId: videoId,
          context: {
            client: {
              clientName: "ANDROID",
              clientVersion: "19.09.37"
            }
          }
        })
      }
    );

    const data = await playerRes.json();
    const tracks = data?.captions?.playerCaptionsTracklistRenderer?.captionTracks;

    if (!tracks || tracks.length === 0) {
      return res.status(404).json({
        error: "No captions found for this video.",
        debug: { hasCaptions: !!data?.captions, topLevelKeys: Object.keys(data || {}) }
      });
    }

    const track = tracks.find(t => t.languageCode === "en") || tracks[0];
    const capRes = await fetch(track.baseUrl);
    const capXML = await capRes.text();

    const cues = [];
    const regex = /<text start="([\d.]+)" dur="([\d.]+)"[^>]*>([^<]*)<\/text>/g;
    let m;
    while ((m = regex.exec(capXML)) !== null) {
      const clean = m[3].replace(/&#39;/g, "'").replace(/&amp;/g, "&").replace(/&quot;/g, '"');
      cues.push({ start: parseFloat(m[1]), end: parseFloat(m[1]) + parseFloat(m[2]), text: clean });
    }

    res.status(200).json({ cues });
  } catch (err) {
    res.status(500).json({ error: "Failed to fetch captions.", debug: err.message });
  }
}
