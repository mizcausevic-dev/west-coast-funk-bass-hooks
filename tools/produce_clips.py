#!/usr/bin/env python3
"""Produce and verify focused four-bar clips for the approved ten-pack batch."""
import argparse
import csv
import hashlib
import json
import zipfile
from pathlib import Path

import build_release as release
import build_footwork as engine

MODES = {
    "dark-edm-chord-vault": ("chords",),
    "nineties-trance-chords-melodies": ("chords", "principal_motif"),
    "bass-house-hooks": ("sub_bass",),
    "tech-house-groove-builder": ("sub_bass",),
    "melodic-house-chord-journeys": ("chords",),
    "house-techno-crossover": ("sub_bass",),
    "hardstyle-anthem-toolkit": ("principal_motif",),
    "disco-funk-chords": ("chords",),
    "progressive-rock-writing-kit": ("principal_motif",),
    "afro-house-inspired-melodies": ("principal_motif",),
    "hip-hop-chord-melody-sketches": ("chords", "principal_motif"),
    "ambientcore-textures": ("chords",),
    "soulful-house-chords": ("chords",),
    "piano-house-hooks": ("principal_motif",),
    "garage-house-grooves": ("sub_bass",),
    "melodic-techno-sequences": ("principal_motif",),
    "dark-techno-melodies": ("principal_motif",),
    "uplifting-trance-leads": ("principal_motif",),
    "afrobeats-inspired-melodies": ("principal_motif",),
    "trap-melody-toolkit": ("principal_motif",),
}
MODES.update({'lo-fi-hip-hop-chords': ('chords',), 'jazz-house-chords': ('chords', 'sub_bass'), 'dark-pop-chords-hooks': ('chords', 'principal_motif'), 'future-garage-chords': ('chords',), 'cinematic-chord-progressions': ('chords',), 'jackin-house-grooves': ('sub_bass',), 'minimal-deep-tech': ('sub_bass',), 'latin-house-inspired-grooves': ('sub_bass',), 'electro-house-leads': ('principal_motif',), 'progressive-house-builds': ('principal_motif',), 'dream-trance-melodies': ('principal_motif',), 'tech-trance-sequences': ('sub_bass',), 'raw-hardstyle-leads': ('principal_motif',), 'melodic-dubstep-chords-leads': ('chords', 'principal_motif'), 'breaks-and-bass-hooks': ('sub_bass',), 'afro-tech-inspired-sequences': ('principal_motif',), 'amapiano-inspired-chords-leads': ('chords', 'principal_motif'), 'afro-fusion-melody-sketches': ('principal_motif',), 'afro-house-inspired-percussion-bass': ('sub_bass',), 'cinematic-world-percussion': ('principal_motif',), 'progressive-metal-riffs': ('principal_motif',), 'alternative-rock-song-starters': ('chords', 'principal_motif'), 'indie-funk-bass-keys': ('chords', 'sub_bass'), 'post-rock-crescendos': ('principal_motif',), 'ambient-guitar-motifs': ('principal_motif',)})
MODES.update({'classic-chicago-house-grooves': ('principal_motif',), 'french-house-chord-stabs': ('chords',), 'funky-house-piano-stabs': ('principal_motif',), 'vocal-garage-house-hooks': ('principal_motif',), 'soulful-disco-house-keys': ('principal_motif',), 'afro-organic-house-motifs': ('principal_motif',), 'balearic-house-chords': ('chords',), 'piano-house-basslines': ('sub_bass',), 'dark-minimal-house-grooves': ('principal_motif',), 'deep-tribal-house-percussion': ('drums',), 'sunset-house-progressions': ('principal_motif',), 'lo-fi-house-chord-loops': ('chords',), 'hypnotic-techno-bass-sequences': ('sub_bass',), 'industrial-techno-rhythms': ('drums',), 'peak-time-techno-riffs': ('principal_motif',), 'dub-techno-chord-textures': ('chords',), 'minimal-detroit-sequences': ('principal_motif',), 'acid-techno-patterns': ('principal_motif',), 'dark-ambient-techno-pulses': ('principal_motif',), 'broken-techno-drum-cells': ('drums',), 'driving-techno-basslines': ('sub_bass',), 'melodic-minimal-techno-motifs': ('principal_motif',), 'warehouse-techno-lead-stabs': ('principal_motif',), 'experimental-techno-textures': ('principal_motif',), 'classic-goa-trance-sequences': ('principal_motif',), 'progressive-psytrance-basslines': ('sub_bass',), 'balearic-trance-melodies': ('principal_motif',), 'euphoric-trance-chord-arcs': ('chords',), 'dark-trance-bass-motifs': ('sub_bass',), 'acid-trance-arpeggios': ('principal_motif',), 'vocal-trance-melody-sketches': ('principal_motif',), 'progressive-trance-builds': ('principal_motif',), 'downtempo-psybient-patterns': ('principal_motif',), 'deep-drum-and-bass-chords': ('chords',), 'dark-jungle-bass-motifs': ('sub_bass',), 'minimal-drum-and-bass-rollers': ('sub_bass',), 'jump-up-bass-hooks': ('sub_bass',), 'drumstep-groove-sketches': ('principal_motif',), 'leftfield-bass-rhythms': ('drums',), 'glitch-hop-basslines': ('sub_bass',), 'uk-grime-bass-hooks': ('sub_bass',), 'future-garage-drum-patterns': ('drums',), 'liquid-breakbeat-melodies': ('principal_motif',), 'half-time-drum-and-bass-riffs': ('sub_bass',), 'soulful-boom-bap-chords': ('chords',), 'jazz-rap-piano-motifs': ('principal_motif',), 'trap-bell-melodies': ('principal_motif',), 'dark-trap-basslines': ('sub_bass',), 'cloud-rap-chord-textures': ('chords',), 'west-coast-funk-bass-hooks': ('sub_bass',), 'memphis-inspired-piano-loops': ('principal_motif',), 'neo-soul-bass-and-chords': ('chords',), 'alternative-r-b-lead-lines': ('principal_motif',), 'lo-fi-guitar-midi-melodies': ('principal_motif',), 'math-metal-polyrhythmic-riffs': ('principal_motif',), 'post-metal-slow-builds': ('principal_motif',), 'indie-rock-chorus-chords': ('chords',), 'dream-pop-guitar-motifs': ('principal_motif',), 'heavy-rock-bass-riffs': ('sub_bass',), 'progressive-rock-keyboard-leads': ('principal_motif',), 'ambient-shoegaze-chords': ('chords',), 'punk-rock-song-sketches': ('principal_motif',), 'funk-rock-basslines': ('sub_bass',), 'darkwave-guitar-motifs': ('principal_motif',), 'dark-cinematic-drones': ('principal_motif',), 'noir-piano-sketches': ('principal_motif',), 'suspense-string-ostinatos': ('principal_motif',), 'orchestral-trailer-pulses': ('principal_motif',), 'ethereal-ambient-chords': ('chords',), 'minimal-piano-fragments': ('principal_motif',), 'space-ambient-sequences': ('principal_motif',), 'meditative-synth-harmony': ('chords',), 'haunting-music-box-motifs': ('principal_motif',), 'atmospheric-soundtrack-bass': ('sub_bass',), 'ambient-bell-arpeggios': ('principal_motif',), 'slow-burn-cinematic-tension': ('principal_motif',)})
END = 4 * release.BAR_TICKS

def make_clip(notes, name):
    raw = engine.common_meta(name)
    for start, duration, pitch, velocity in notes:
        raw.extend([(start, 3, bytes([0x99 if "drum" in name else 0x90, pitch, velocity])), (start+duration, 2, bytes([0x89 if "drum" in name else 0x80, pitch, 0]))])
    return engine.midi(0, [engine.track(raw, end_tick=END)])

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, required=True)
    ap.add_argument("--pack", choices=MODES, required=True)
    args = ap.parse_args()
    root = args.root.resolve()
    pack = dict(release.PACKS[args.pack])
    pack["slug"] = args.pack
    studies = release.configure(root, pack)
    folder = root / "clips"
    folder.mkdir(exist_ok=False)
    records = []
    for study_index, study in enumerate(studies):
        score = release.compose(study, study_index, pack["pattern"])
        for kind in MODES[args.pack]:
            for variation in range(4):
                notes = []
                if kind == "chords":
                    section_start = (8 + variation * 4) * release.BAR_TICKS
                    for event in score["chord_pulse"]:
                        if section_start <= event["start"] < section_start + END:
                            local = event["start"] - section_start
                            notes.append((local, min(event["duration"], END-local), event["pitch"], event["velocity"]))
                    # Revoice the lowest tones and displace each phrase slightly.
                    # Both choices vary by study and variation, while preserving
                    # the pack's own chord rhythm and pitch classes.
                    grouped = {}
                    for item in notes:
                        grouped.setdefault(item[0], []).append(item)
                    shift = (49 * 3 + study_index * 11 + variation * 17) % 64
                    notes = []
                    for offset, chord in sorted(grouped.items()):
                        chord.sort(key=lambda n: n[2])
                        inversion = (study_index + variation + offset // release.BAR_TICKS) % len(chord)
                        for rank, (_, duration, pitch, velocity) in enumerate(chord):
                            local = offset + shift
                            if local < END:
                                notes.append((local, min(duration, END-local), pitch + (12 if rank < inversion else 0), min(127, velocity + variation * 2)))
                else:
                    start = (8 + variation*4) * release.BAR_TICKS
                    for event in score[kind]:
                        if start <= event["start"] < start + END:
                            local = event["start"] - start
                            # Reserve a different bar of space in each bass study.
                            if kind == "sub_bass" and study_index and local // release.BAR_TICKS == study_index and local % release.BAR_TICKS == 0:
                                continue
                            notes.append((local, min(event["duration"], END-local), event["pitch"], event["velocity"]))
                if kind == "drums":
                    notes = [n for n in notes if not (n[2] == 42 and (n[0] // 480 + study_index + variation) % 5 == 0)]
                    notes.append((120 + study_index * 480 + variation * 90, 45, 39, 50 + variation * 3))
                    notes.append(((49 % 16) * 120 + 45, 30, 46, 48 + 49 % 12))
                if kind in ("sub_bass", "principal_motif") and len(notes) >= 4:
                    notes = [n for j, n in enumerate(notes) if j % 8 != variation]
                    shift = (49 * 3 + study_index * 11 + variation * 17) % 64
                    notes = [(start + shift, min(duration, END-start-shift), pitch, velocity) for start, duration, pitch, velocity in notes if start + shift < END]
                if not notes:
                    raise ValueError(f"Empty clip: {study['id']} {kind} {variation}")
                label = "drum-pattern" if kind == "drums" else ("chord-progression" if kind == "chords" else ("bass-hook" if kind == "sub_bass" else "melody"))
                path = folder / f"{study['id']}-{label}-{variation+1:02d}.mid"
                path.write_bytes(make_clip(notes, f"{study['id']}-{label}-{variation+1:02d}"))
                parsed = engine.parse_midi(path)
                actual = parsed["tracks"][0]["events"]
                if parsed["format"] != 0 or parsed["division"] != 480 or parsed["tracks"][0]["eot"] != END or len(actual) != len(notes) or any(e["duration"] <= 0 for e in actual):
                    raise ValueError(f"Clip validation failed: {path.name}")
                records.append({"path":path.relative_to(root).as_posix(),"study":study["id"],"kind":label,"bars":4,"tempo_bpm":pack["bpm"],"notes":len(notes),"sha256":hashlib.sha256(path.read_bytes()).hexdigest()})
    with (root/"catalog"/"clip-index.csv").open("w",encoding="utf-8",newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(records[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(records)
    report = {"status":"PASS","files_checked":len(records),"checks":["Reopened each MIDI file","Format 0, 480 PPQ, four-bar end tick","Paired positive-duration notes","Nonempty note events","SHA-256"],"limitations":["Technical validation does not establish listening quality."]}
    (root/"checks"/"clip-validation.json").write_text(json.dumps(report,indent=2)+"\n",encoding="utf-8",newline="\n")
    archive = root/"downloads"/f"{args.pack}-midi.zip"
    with zipfile.ZipFile(archive,"a",compression=zipfile.ZIP_DEFLATED) as bundle:
        for record in records:
            bundle.write(root/record["path"],record["path"])
        bundle.write(root/"catalog"/"clip-index.csv","catalog/clip-index.csv")
    with zipfile.ZipFile(archive) as bundle:
        for record in records:
            if hashlib.sha256(bundle.read(record["path"])).hexdigest() != record["sha256"]:
                raise ValueError("Archive clip hash mismatch")
    count = 28 + len(records)
    readme = root/"README.md"
    readme.write_text(readme.read_text(encoding="utf-8")+f"\n## Focused clips\n\nThis pack also includes {len(records)} four-bar standalone MIDI clips in `clips/`, indexed in `catalog/clip-index.csv` and included in the main ZIP. These are derived from the pack's harmonic and melodic material. The download contains {count} MIDI files in total. Clip integrity results are in `checks/clip-validation.json`.\n",encoding="utf-8",newline="\n")
    site = root/"index.html"
    html = site.read_text(encoding="utf-8").replace("Download 28-MIDI archive", f"Download {count}-MIDI archive")
    html = html.replace("</main><footer>", f'<section><h2>Focused MIDI clips</h2><p>{len(records)} four-bar clips are included in the download. <a href="catalog/clip-index.csv">Browse the clip index</a> · <a href="checks/clip-validation.json">Clip validation</a></p></section></main><footer>')
    site.write_text(html,encoding="utf-8",newline="\n")
    release.write_checksums(root)
    print(json.dumps({"pack":args.pack,"clips":len(records),"total_midi":count,"status":"PASS"}))

if __name__ == "__main__":
    main()
