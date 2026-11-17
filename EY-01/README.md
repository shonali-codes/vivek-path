# EY-01 · A Boon at Dawn

Reel builder for *Swami Vivekananda — Who, before What* (@coffeehouseadda).

```
assets/   EY-01_shot1..8.jpg, EY-01_VO.wav, [EY-01_bed_bhairav.wav]   (audio not committed)
script.json        segment text (source of truth for captions)
tools/align.py     forced alignment of VO vs script (PocketSphinx) -> build/words.json
tools/build.py     render: Ken Burns, crossfades, word-by-word captions, title, end card, mix + master
fonts/             Cormorant Garamond (SIL OFL)
```

Rebuild:
```
pip install pocketsphinx numpy pillow
python3 tools/align.py assets/EY-01_VO.wav build/words.json
python3 tools/build.py            # -> out/EY-01_A-Boon-at-Dawn.mp4
python3 tools/build.py --stills   # quick review frames
```
If `assets/EY-01_bed_bhairav.wav` is present, it is mixed in automatically: normalised to
~-19 LUFS, ducked under the VO (sidechain), 1.5 s fade-in, 2.5 s fade-out over the end card.
The final mix is mastered to -14 LUFS (sample peak ≈ -1.3 dBFS). Music bed log ID: EY-bed-bhairav-01.
