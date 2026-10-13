# Buddy Day Zero 🤖

A curious, standalone desktop companion with an evolving personality.

## Development and releases

Windows and Raspberry Pi builds share the same Python core. GitHub Releases hosts verified application updates.

**Never commit** `.env`, `data/`, personal databases, or API keys.

See `.github/workflows/release.yml` for the automated release packaging workflow.


## Buddy Day Zero v0.23.8 — Conversation & Presentation

- Compact floating Buddy and his expressive face remain unchanged in size.
- His replies now appear in dark, short comic bubbles next to his face, with
  tails oriented toward Buddy and timed approximately to spoken audio.
- Clicking **Record** in Talk starts Smart Listening. Speak and pause; a local
  audio-level detector will stop and transcribe the turn automatically. Clicking
  the button again cancels the recording.
- Use **Start Conversation Mode** in Talk or in Buddy's right-click menu to
  continue talking hands-free across replies. **End Conversation Mode** or
  "Goodbye Buddy" ends the session. Silence times out rather than recording forever.
- Opt-in offline **Hey Buddy** wake phrase is available in Settings. First-time
  enabling explicitly asks permission to download a local Vosk English model
  (roughly 40 MB) and install the Python Vosk package if necessary. Ambient
  wake audio is processed locally, never continuously uploaded for recognition.
  Recognition quality depends on microphone quality, noise, and the offline model.
- The updater asks approval once. During download his eyes become progress rings.
  He announces when the verified update is ready, then restarts. Only *after*
  successful installation does the new app show 100% success sparkles and a ding.

Voice playback and transcription use the OpenAI API and incur associated API
usage costs. Phrased speech bubbles are timed to the synthesized WAV's total
duration, not word-level timestamps; their synchronization is approximate.

To access controls, **click Buddy** to open Talk or **right-click** him for
Settings, updates, Conversation Mode and Quit. Day Zero memory and .env are not
included in releases. Changes are tested on Linux with headless Qt;
the Windows/Pi hardware paths still need hands-on testing.
