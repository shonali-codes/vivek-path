# Swami Vivekananda — Who, before What · @coffeehouseadda

Reel builds for the series. One shared kit (`reelkit/`), one directory per episode.

```
reelkit/
  align.py      forced alignment of the VO against script.json (PocketSphinx) -> <EP>/build/words.json
  build.py      render: Ken Burns, crossfades, word-by-word captions, hook/title/end cards, mix + master
  extra.dict    pronunciations for names and Sanskrit terms the stock dictionary lacks
  fonts/        Cormorant Garamond (SIL OFL)
EY-01/  EY-02/ …
  episode.json  per-episode look: gold terms, cold open / opener / title cards, soft dissolve, focus points
  script.json   segment text = caption text
  assets/       <ID>_shot<N>.jpg|png, <ID>_VO.wav, <ID>_bed_<raga>.wav   (audio is not committed)
```

Build an episode:
```
pip install pocketsphinx numpy pillow
python3 reelkit/align.py EY-02          # if it lists unknown words, add them to reelkit/extra.dict
python3 reelkit/build.py EY-02 --stills # quick review frames -> EY-02/build/stills/
python3 reelkit/build.py EY-02          # -> EY-02/out/EY-02_<slug>.mp4
```

Output: 1080×1920, 30 fps, H.264 (≤6 Mbps), AAC 256k, mastered to −14 LUFS.
Music bed: normalised, ducked under the VO (~10 dB below speech, blooms in pauses), 1.5 s fade-in,
2.5 s fade-out over the end card; a bed shorter than the reel is extended with an 8 s crossfade.
Music log IDs: EY-bed-bhairav-01, EY-bed-yaman-02.
