import { YoutubeTranscript } from "youtube-transcript";

export default async function handler(req, res) {
  const { videoId } = req.query;
  res.setHeader("Cache-Control", "no-store");

  if (!videoId) {
    return res.status(400).json({ error: "Missing videoId" });
  }

  try {
    const transcript = await YoutubeTranscript.fetchTranscript(videoId);

    if (!transcript || transcript.length === 0) {
      return res.status(404).json({ error: "No captions found for this video." });
    }

    const cues = transcript.map(item => ({
      start: item.offset / 1000,
      end: (item.offset + item.duration) / 1000,
      text: item.text
    }));

    res.status(200).json({ cues });
  } catch (err) {
    res.status(500).json({ error: "Couldn't load captions.", debug: err.message });
  }
}
