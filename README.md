# West Coast Funk Bass Hooks Studies

Four original note-only MIDI studies for producers who need the musical structure documented as carefully as the files.

**Live catalog:** https://mizcausevic-dev.github.io/west-coast-funk-bass-hooks/

This is a bounded symbolic-composition release, not a sample pack, recording, or claim to define a genre, its history or its communities.

## The studies

| Study | Pitch collection | Frame |
| --- | --- | --- |
| z5001 West Coast Funk Bass Hooks Opening | D pack-local pitch collection | 32 bars · 88 BPM · 4/4 |
| z5002 West Coast Funk Bass Hooks Variation | F pack-local pitch collection | 32 bars · 88 BPM · 4/4 |
| z5003 West Coast Funk Bass Hooks Contrast | G# pack-local pitch collection | 32 bars · 88 BPM · 4/4 |
| z5004 West Coast Funk Bass Hooks Return | D# pack-local pitch collection | 32 bars · 88 BPM · 4/4 |

The release contains 28 study MIDI files: six Format 0 role exports and one Format 1 combined arrangement per study. It also contains canonical event CSVs, structural/harmonic/drum-map records, patch recipes, checksums, an original SVG cover, a simple-synthesis preview, draft editorial copy and one ZIP.

## Start here

1. Open the live catalog or download `downloads/west-coast-funk-bass-hooks-midi.zip`.
2. Choose either a combined arrangement or the separate part files. **Do not stack the part files on the combined file.**
3. Read `catalog/patch-recipes.json` for channel/role mappings, and `checks/validation-report.json` before relying on a technical claim.

## File contract

- 480 PPQ, 4/4, 88 BPM, 61,440 end ticks per study.
- Five pitched roles use user-facing channels 1–5 (wire values 0–4); drums use user-facing channel 10 (wire value 9).
- Bass and principal melody are monophonic. No program changes, controllers, pitch bends, keyswitches or SysEx are present.
- Original symbolic studies; genre labels are production directions, not cultural authority.

## Technical verification boundary

The validator reopens final bytes and checks MIDI count, Format 0/1 shape, PPQ, tempo, meter, named combined tracks, event timing, note pairing, role channels, monophony, same-pitch overlap, CSV parity, region coverage, drum-map coverage, ZIP paths, preview decode and checksum records. It also runs a known-invalid same-pitch-overlap fixture.

It does **not** certify groove, musical quality, commercial suitability, physical playability, cultural authenticity or copyright clearance. Duplicate-motif results are only a bounded structural review. Automated checks may pass while human listening remains unperformed.

The preview is generated from the first study's committed MIDI with a documented simple synthesizer. It is a **preview, not a master**.

## Rebuild

```powershell
python tools/build_release.py --pack west-coast-funk-bass-hooks
python tools/validate_release.py
python -m http.server 4173
```

`tools/build_footwork.py` is the local MIDI byte engine retained from the initial release; `tools/build_release.py` is the profile-driven release writer. The committed outputs, rather than an external service, are the build evidence.

## Focused clips

This pack also includes 16 four-bar standalone MIDI clips in `clips/`, indexed in `catalog/clip-index.csv` and included in the main ZIP. These are derived from the pack's harmonic and melodic material. The download contains 44 MIDI files in total. Clip integrity results are in `checks/clip-validation.json`.

## Media

The 18-second animated MIDI-note visualizer uses the first 18 seconds of the canonical MIDI-derived preview. `film/video-manifest.json` records the source hash, excerpt, encoding and caption. Raster art is ai-generated abstract illustration, not a photograph. Social captions and article are drafts. No human listening review is claimed.

To regenerate media after rebuilding, preserve the source image and run `python tools/polish_release.py --root . --image art/illustration-source.png --art-kind ai`. Pillow and FFmpeg are required.
