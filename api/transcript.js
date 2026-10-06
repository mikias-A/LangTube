import { Innertube } from "youtubei.js";

export default async function handler(req, res) {
  const { videoId } = req.query;
  res.setHeader("Cache-Control", "no-store");

  if (!videoId) {
    return res.status(400).json({ error: "Missing videoId" });
  }

  try {
    const yt = await Innertube.create({ lang: "en", location: "US", retrieve_player: false });
    const info = await yt.getInfo(videoId);
    const transcriptData = await info.getTranscript();

    const segments = transcriptData?.transcript?.content?.body?.initial_segments;

    if (!segments || segments.length === 0) {
      return res.status(404).json({
        error: "No captions found for this video.",
        debug: { hasTranscriptData: !!transcriptData, keys: transcriptData ? Object.keys(transcriptData) : [] }
      });
    }

    const cues = segments.map(seg => ({
      start: Number(seg.start_ms) / 1000,
      end: Number(seg.end_ms) / 1000,
      text: seg.snippet?.text ?? seg.snippet?.toString?.() ?? ""
    }));

    res.status(200).json({ cues });
  } catch (err) {
    res.status(500).json({ error: "Couldn't load captions.", debug: err.message });
  }
}
