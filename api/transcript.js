export default async function handler(req, res) {
  const { videoId } = req.query;

  if (!videoId) {
    return res.status(400).json({ error: "Missing videoId" });
  }

  try {
    const listRes = await fetch(`https://www.youtube.com/api/timedtext?type=list&v=${videoId}`);
    const listXML = await listRes.text();
    const langMatch = listXML.match(/lang_code="([^"]+)"/);

    if (!langMatch) {
      return res.status(404).json({ error: "No captions found for this video." });
    }

    const langCode = langMatch[1];
    const capRes = await fetch(`https://www.youtube.com/api/timedtext?lang=${langCode}&v=${videoId}`);
    const capXML = await capRes.text();

    const cues = [];
    const regex = /<text start="([\d.]+)" dur="([\d.]+)"[^>]*>([^<]*)<\/text>/g;
    let match;
    while ((match = regex.exec(capXML)) !== null) {
      const clean = match[3]
        .replace(/&#39;/g, "'")
        .replace(/&amp;/g, "&")
        .replace(/&quot;/g, '"');
      cues.push({ start: parseFloat(match[1]), end: parseFloat(match[1]) + parseFloat(match[2]), text: clean });
    }

    res.status(200).json({ cues });
  } catch (err) {
    res.status(500).json({ error: "Failed to fetch captions." });
  }
}
