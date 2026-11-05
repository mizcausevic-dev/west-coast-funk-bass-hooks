#!/usr/bin/env python3
"""Deterministic builder for Footwork Codex."""
from __future__ import annotations

import csv
import hashlib
import json
import math
import shutil
import struct
import subprocess
import sys
import wave
import zipfile
from array import array
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PPQ = 480
BAR_TICKS = 1920
BARS = 32
END_TICK = 61440
BPM = 160
TEMPO_US = 375000
VERSION = "1.0.0-Codex"
ROLES = [
    ("chord_pulse", "Clipped synthetic chord", 0, 1, 3),
    ("sub_bass", "Sub bass", 1, 2, 1),
    ("principal_motif", "Principal melody", 2, 3, 1),
    ("vocal_like_synth", "Original vocal-like synth", 3, 4, 1),
    ("counter_texture", "Selective counter texture", 4, 5, 2),
    ("drums", "Dry percussion", 9, 10, 4),
]
ROLE = {item[0]: item for item in ROLES}
SECTIONS = [
    ("introduction", "Introduction", 0, 8),
    ("statement", "Statement", 8, 8),
    ("contrast", "Contrast", 16, 8),
    ("transformed_return", "Transformed return", 24, 8),
]
STUDIES = [
    {"id": "f01", "slug": "cross-grid", "title": "Cross Grid", "tonic": "D",
     "collection": "D natural minor", "chords": [[50,53,57],[48,52,55],[46,50,53],[45,48,52]],
     "bass": [26,24,22,21], "motif": [74,77,81,79,77,74], "voice": [86,84,81,84],
     "texture": [69,72,74,77], "pulses": [120,900,1500], "motifs": [300,510,810,1110,1410,1650],
     "intent": "Kick accents step around a steady grid while the motif crosses the drum phrase boundary."},
    {"id": "f02", "slug": "split-signal", "title": "Split Signal", "tonic": "F",
     "collection": "F Dorian", "chords": [[53,56,60],[55,58,62],[51,55,58],[53,57,60]],
     "bass": [29,31,27,29], "motif": [77,80,82,84,82,80], "voice": [89,87,84,87],
     "texture": [72,75,77,80], "pulses": [0,660,1320], "motifs": [180,420,660,1080,1320,1740],
     "intent": "Compact answers interrupt one another while the bass repeats a small contour."},
    {"id": "f03", "slug": "redline-gap", "title": "Redline Gap", "tonic": "B",
     "collection": "B Phrygian", "chords": [[47,50,54],[48,52,55],[45,48,52],[47,51,54]],
     "bass": [23,24,21,23], "motif": [71,72,74,76,74,72], "voice": [83,84,86,84],
     "texture": [66,69,71,74], "pulses": [240,1080,1560], "motifs": [90,330,570,930,1290,1590],
     "intent": "A long gap after the snare cell leaves the stable grid audible without filler."},
    {"id": "f04", "slug": "lattice-return", "title": "Lattice Return", "tonic": "A",
     "collection": "A natural minor", "chords": [[45,48,52],[43,47,50],[41,45,48],[40,43,47]],
     "bass": [21,19,17,16], "motif": [69,72,76,79,76,72], "voice": [81,79,76,79],
     "texture": [64,67,69,72], "pulses": [60,780,1380], "motifs": [240,480,960,1200,1440,1680],
     "intent": "The transformed return restates the phrase in a tighter high register then leaves space."},
]
DRUM_MAP = [
    {"pitch": 36, "name": "Kick", "purpose": "low pulse"},
    {"pitch": 38, "name": "Snare", "purpose": "dry backbeat cell"},
    {"pitch": 39, "name": "Clap", "purpose": "short answer"},
    {"pitch": 42, "name": "Closed hi-hat", "purpose": "grid reference"},
    {"pitch": 46, "name": "Open hi-hat", "purpose": "transition only"},
]


def relative(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def write_json(path: Path, data: object) -> None:
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def vlq(value: int) -> bytes:
    if value < 0:
        raise ValueError("negative variable length quantity")
    data = [value & 127]
    value >>= 7
    while value:
        data.append((value & 127) | 128)
        value >>= 7
    return bytes(reversed(data))


def meta(kind: int, body: bytes) -> bytes:
    return bytes([255, kind]) + vlq(len(body)) + body


def track(events: list[tuple[int, int, bytes]], end_tick: int = END_TICK) -> bytes:
    previous = 0
    payload = bytearray()
    for tick, priority, data in sorted(events, key=lambda item: (item[0], item[1])):
        if tick < previous or tick > end_tick:
            raise ValueError("event is outside study")
        payload.extend(vlq(tick - previous))
        payload.extend(data)
        previous = tick
    payload.extend(vlq(end_tick - previous))
    payload.extend(meta(47, b""))
    return b"MTrk" + struct.pack(">I", len(payload)) + payload


def midi(fmt: int, tracks: list[bytes]) -> bytes:
    return b"MThd" + struct.pack(">IHHH", 6, fmt, len(tracks), PPQ) + b"".join(tracks)


def common_meta(name: str) -> list[tuple[int, int, bytes]]:
    return [
        (0, 0, meta(3, name.encode("ascii"))),
        (0, 1, meta(81, TEMPO_US.to_bytes(3, "big"))),
        (0, 2, meta(88, bytes([4, 2, 24, 8]))),
    ]


def note(start: int, channel: int, pitch: int, duration: int, velocity: int, ornament: bool = False) -> dict:
    if not 0 <= channel <= 15 or not 0 <= pitch <= 127 or not 1 <= velocity <= 127:
        raise ValueError("invalid note value")
    if start < 0 or duration <= 0 or start + duration > END_TICK:
        raise ValueError("note is outside study")
    return {"start": start, "duration": duration, "pitch": pitch, "velocity": velocity, "channel": channel, "ornament": ornament}


def add(score: dict[str, list[dict]], role: str, start: int, pitch: int, duration: int, velocity: int, ornament: bool = False) -> None:
    score[role].append(note(start, ROLE[role][2], pitch, duration, velocity, ornament))


def region_name(bar: int) -> str:
    for key, _, start, length in SECTIONS:
        if start <= bar < start + length:
            return key
    raise ValueError("invalid bar")


def compose(study: dict, study_index: int) -> dict[str, list[dict]]:
    score = {role[0]: [] for role in ROLES}
    for bar in range(BARS):
        base = bar * BAR_TICKS
        section = region_name(bar)
        chord_index = (bar // 4 + study_index) % 4
        chord = study["chords"][chord_index]
        for ordinal, offset in enumerate(study["pulses"]):
            if (section == "introduction" and bar % 2 and ordinal > 0) or (section == "contrast" and ordinal == 1):
                continue
            for pitch in chord:
                add(score, "chord_pulse", base + offset, pitch, 150 if ordinal != 2 else 210, 74 + ordinal * 8)
        for ordinal, offset in enumerate([0, 840, 1440] if bar % 2 == 0 else [0, 660, 1320]):
            if section == "introduction" and ordinal == 1:
                continue
            displacement = 60 if section == "transformed_return" and ordinal == 2 else 0
            add(score, "sub_bass", base + offset + displacement, study["bass"][chord_index] + (12 if ordinal == 2 else 0), 240, 86 + ordinal * 5)
        if not (section == "introduction" and bar < 4):
            for ordinal, offset in enumerate(study["motifs"]):
                if section == "contrast" and ordinal in (1, 4):
                    continue
                pitch = study["motif"][(ordinal + bar + (1 if section == "transformed_return" else 0)) % 6]
                duration = 180 if ordinal % 3 == 0 else 120
                add(score, "principal_motif", base + offset, pitch, duration, 78 + ordinal % 3 * 9)
                if ordinal in (2, 5) and section in ("statement", "transformed_return"):
                    add(score, "principal_motif", base + offset + duration, pitch + 2, 60, 57, True)
        if section in ("statement", "contrast", "transformed_return") and bar % 2:
            for ordinal, offset in enumerate([360, 1080] if section != "contrast" else [600, 1380]):
                add(score, "vocal_like_synth", base + offset, study["voice"][(bar + ordinal) % 4], 180, 68 + ordinal * 10)
        if section in ("contrast", "transformed_return") and bar % 2 == 0:
            offset = 1320 if section == "contrast" else 1140
            pitch = study["texture"][(bar // 2) % 4]
            add(score, "counter_texture", base + offset, pitch, 300, 51)
            add(score, "counter_texture", base + offset, pitch + 7, 300, 46)
        for ordinal, offset in enumerate([0, 780, 1440] if bar % 2 == 0 else [0, 540, 1320]):
            if section == "contrast" and ordinal == 1:
                continue
            add(score, "drums", base + offset, 36, 60, 104 - ordinal * 8)
        for ordinal, offset in enumerate([480, 1260] if bar % 2 == 0 else [600, 1380]):
            add(score, "drums", base + offset, 38, 60, 88 + ordinal * 6)
            if section in ("statement", "transformed_return") and ordinal == 1:
                add(score, "drums", base + offset + 60, 39, 45, 63)
        for offset in range(240, BAR_TICKS, 240):
            if section == "introduction" and bar < 4 and offset in (720, 1200):
                continue
            add(score, "drums", base + offset, 42, 36, 48 + (bar + offset // 240) % 3 * 7)
        if bar in (7, 15, 23, 31):
            for offset in (1560, 1800):
                add(score, "drums", base + offset, 42, 30, 64)
            add(score, "drums", base + 1500, 46, 150, 63)
            add(score, "drums", base + 1680, 46, 30, 64)
    return score


def assert_score(score: dict[str, list[dict]]) -> None:
    for role, events in score.items():
        by_pitch: dict[int, int] = {}
        active = 0
        for event in sorted(events, key=lambda item: (item["start"], item["pitch"])):
            if event["start"] < by_pitch.get(event["pitch"], -1):
                raise ValueError(role + " has same pitch overlap")
            by_pitch[event["pitch"]] = event["start"] + event["duration"]
            if role in ("sub_bass", "principal_motif") and event["start"] < active:
                raise ValueError(role + " is not monophonic")
            if role in ("sub_bass", "principal_motif"):
                active = event["start"] + event["duration"]


def role_track(role: str, events: list[dict], with_meta: bool = True) -> bytes:
    channel = ROLE[role][2]
    raw = common_meta(role) if with_meta else [(0, 0, meta(3, role.encode("ascii")))]
    for event in events:
        raw.append((event["start"], 3, bytes([144 | channel, event["pitch"], event["velocity"]])))
        raw.append((event["start"] + event["duration"], 2, bytes([128 | channel, event["pitch"], 0])))
    return track(raw)


def write_midi(study: dict, score: dict[str, list[dict]]) -> tuple[list[Path], Path]:
    folder = ROOT / "midi" / (study["id"] + "-" + study["slug"])
    folder.mkdir(parents=True, exist_ok=True)
    parts = []
    for role, _, _, _, _ in ROLES:
        path = folder / (role + ".mid")
        path.write_bytes(midi(0, [role_track(role, score[role])]))
        parts.append(path)
    metadata = track(common_meta(study["id"] + " metadata") + [(0, 3, meta(1, b"Footwork Codex original score"))])
    combined = folder / (study["id"] + "-" + study["slug"] + "-combined.mid")
    combined.write_bytes(midi(1, [metadata] + [role_track(role, score[role], False) for role, *_ in ROLES]))
    return parts, combined


def read_vlq(data: bytes, position: int) -> tuple[int, int]:
    value = 0
    while True:
        if position >= len(data):
            raise ValueError("truncated variable length quantity")
        byte = data[position]
        position += 1
        value = value << 7 | byte & 127
        if not byte & 128:
            return value, position


def parse_midi(path: Path) -> dict:
    data = path.read_bytes()
    if data[:4] != b"MThd" or len(data) < 14:
        raise ValueError(str(path) + " has no MIDI header")
    length, fmt, track_count, division = struct.unpack(">IHHH", data[4:14])
    if length != 6:
        raise ValueError("unsupported header length")
    position = 14
    tracks = []
    for _ in range(track_count):
        if data[position:position + 4] != b"MTrk":
            raise ValueError("missing MIDI track")
        size = struct.unpack(">I", data[position + 4:position + 8])[0]
        chunk = data[position + 8:position + 8 + size]
        position += 8 + size
        cursor, tick, running = 0, 0, None
        name, eot, forbidden = "", None, []
        metas, events, open_notes = [], [], {}
        while cursor < len(chunk):
            delta, cursor = read_vlq(chunk, cursor)
            tick += delta
            lead = chunk[cursor]
            if lead >= 128:
                status = lead
                cursor += 1
                if status < 240:
                    running = status
            elif running is not None:
                status = running
            else:
                raise ValueError("invalid running status")
            if status == 255:
                kind = chunk[cursor]
                cursor += 1
                body_size, cursor = read_vlq(chunk, cursor)
                body = chunk[cursor:cursor + body_size]
                cursor += body_size
                metas.append((tick, kind, body))
                if kind == 3:
                    name = body.decode("ascii", errors="replace")
                if kind == 47:
                    eot = tick
                continue
            if status in (240, 247):
                body_size, cursor = read_vlq(chunk, cursor)
                cursor += body_size
                forbidden.append("sysex")
                continue
            family, channel = status & 240, status & 15
            data_size = 1 if family in (192, 208) else 2
            body = chunk[cursor:cursor + data_size]
            cursor += data_size
            if len(body) != data_size:
                raise ValueError("truncated channel event")
            if family in (176, 192, 208, 224):
                forbidden.append(hex(family))
            pitch, value = body[0], body[1] if data_size == 2 else 0
            key = (channel, pitch)
            if family == 144 and value:
                open_notes.setdefault(key, []).append((tick, value))
            elif family == 128 or family == 144 and value == 0:
                if not open_notes.get(key):
                    raise ValueError("unmatched note off")
                start, velocity = open_notes[key].pop(0)
                events.append({"start": start, "duration": tick - start, "pitch": pitch, "velocity": velocity, "channel": channel})
        if any(open_notes.values()):
            raise ValueError("unpaired note on")
        tracks.append({"name": name, "metas": metas, "events": events, "eot": eot, "forbidden": forbidden})
    if position != len(data):
        raise ValueError("trailing bytes after MIDI tracks")
    return {"format": fmt, "division": division, "tracks": tracks}


def write_catalog_csvs(all_scores: dict[str, dict[str, list[dict]]]) -> None:
    catalog = ROOT / "catalog"
    with (catalog / "study-index-Codex.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["study_id", "title", "collection", "tonic", "tempo_bpm", "meter", "ppq", "bars", "end_tick", "combined_path", "roles"])
        writer.writeheader()
        for study in STUDIES:
            writer.writerow({"study_id": study["id"], "title": study["title"], "collection": study["collection"], "tonic": study["tonic"], "tempo_bpm": BPM, "meter": "4/4", "ppq": PPQ, "bars": BARS, "end_tick": END_TICK, "combined_path": "midi/" + study["id"] + "-" + study["slug"] + "/" + study["id"] + "-" + study["slug"] + "-combined.mid", "roles": "; ".join(role[0] for role in ROLES)})
    with (catalog / "note-events-Codex.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["study_id", "role", "user_facing_channel", "start_tick", "duration_tick", "pitch", "velocity", "ornament"])
        writer.writeheader()
        for study in STUDIES:
            for role, _, _, display, _ in ROLES:
                for event in sorted(all_scores[study["id"]][role], key=lambda item: (item["start"], item["pitch"])):
                    writer.writerow({"study_id": study["id"], "role": role, "user_facing_channel": display, "start_tick": event["start"], "duration_tick": event["duration"], "pitch": event["pitch"], "velocity": event["velocity"], "ornament": str(event["ornament"]).lower()})
    with (catalog / "structural-regions-Codex.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["study_id", "region", "display_name", "start_bar", "bars", "start_tick", "end_tick"])
        writer.writeheader()
        for study in STUDIES:
            for key, label, start, length in SECTIONS:
                writer.writerow({"study_id": study["id"], "region": key, "display_name": label, "start_bar": start + 1, "bars": length, "start_tick": start * BAR_TICKS, "end_tick": (start + length) * BAR_TICKS})
    with (catalog / "harmonic-events-Codex.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["study_id", "bar", "start_tick", "tonic", "collection", "chord_pitches", "intent"])
        writer.writeheader()
        for study_index, study in enumerate(STUDIES):
            for bar in range(BARS):
                chord = study["chords"][(bar // 4 + study_index) % 4]
                writer.writerow({"study_id": study["id"], "bar": bar + 1, "start_tick": bar * BAR_TICKS, "tonic": study["tonic"], "collection": study["collection"], "chord_pitches": " ".join(str(pitch) for pitch in chord), "intent": study["intent"]})
    with (catalog / "drum-map-Codex.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["midi_pitch", "name", "purpose"])
        writer.writeheader()
        writer.writerows({"midi_pitch": row["pitch"], "name": row["name"], "purpose": row["purpose"]} for row in DRUM_MAP)
    recipes = {
        "renderer": "footwork-simple-synth-Codex 1.0.0",
        "midi_policy": "No program changes, controllers, pitch bends, keyswitches, or SysEx in symbolic exports.",
        "gm_fallback": "Mappings are not encoded. A generic player may use its default piano-like pitched sound and GM-style channel 10 percussion.",
        "roles": [{"role": role, "description": description, "wire_channel": wire, "user_facing_channel": display, "polyphony_cap": cap} for role, description, wire, display, cap in ROLES],
        "gain_stages": {"role_gain_before_velocity": {"chord_pulse": 0.045, "sub_bass": 0.11, "principal_motif": 0.055, "vocal_like_synth": 0.042, "counter_texture": 0.03, "drums": 0.10}, "velocity_scaling": "velocity / 127", "sum_processing": "clamped to +/-0.95 before PCM encoding", "loudness_claim": "none"},
    }
    write_json(catalog / "patch-recipes-Codex.json", recipes)


def make_zip(parts: list[Path], combined: list[Path]) -> Path:
    archive = ROOT / "downloads" / "footwork-codex-midi.zip"
    metadata = [ROOT / "catalog" / name for name in ["study-index-Codex.csv", "note-events-Codex.csv", "structural-regions-Codex.csv", "harmonic-events-Codex.csv", "drum-map-Codex.csv", "patch-recipes-Codex.json"]]
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as output:
        for path in parts + combined + metadata:
            output.write(path, relative(path))
    return archive


def run(args: list[str]) -> None:
    result = subprocess.run(args, cwd=ROOT, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError("command failed: " + " ".join(args) + "\n" + result.stderr[-3000:])


def probe(path: Path) -> dict:
    binary = shutil.which("ffprobe")
    if not binary:
        raise RuntimeError("ffprobe missing")
    result = subprocess.run([binary, "-v", "error", "-show_entries", "format=duration:stream=codec_type,codec_name,width,height", "-of", "json", str(path)], capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def render_preview(source: Path) -> tuple[Path, dict]:
    parsed = parse_midi(source)
    source_events = {row["name"]: row["events"] for row in parsed["tracks"] if row["name"] in ROLE}
    rate = 44100
    duration = END_TICK / PPQ * TEMPO_US / 1_000_000
    samples = array("f", [0.0]) * int((duration + .5) * rate)

    def frequency(pitch: int) -> float:
        return 440 * 2 ** ((pitch - 69) / 12)

    def synth(event: dict, role: str) -> None:
        start = int(event["start"] / PPQ * TEMPO_US / 1_000_000 * rate)
        frames = max(1, int(event["duration"] / PPQ * TEMPO_US / 1_000_000 * rate))
        end = min(len(samples), start + frames)
        level = {"chord_pulse": .045, "sub_bass": .11, "principal_motif": .055, "vocal_like_synth": .042, "counter_texture": .03, "drums": .10}[role] * event["velocity"] / 127
        pitch_frequency = frequency(event["pitch"])
        for index in range(start, end):
            local = (index - start) / max(1, end - start)
            seconds = (index - start) / rate
            envelope = min(1, seconds / .008) * (1 - local) ** (0.65 if role == "sub_bass" else 1.2)
            if role == "sub_bass":
                value = math.sin(2 * math.pi * pitch_frequency * seconds)
            elif role == "chord_pulse":
                value = math.sin(2 * math.pi * pitch_frequency * seconds) + .35 * math.sin(4 * math.pi * pitch_frequency * seconds)
            elif role == "principal_motif":
                value = 2 / math.pi * math.asin(math.sin(2 * math.pi * pitch_frequency * seconds))
            elif role == "vocal_like_synth":
                value = math.sin(2 * math.pi * pitch_frequency * seconds + .18 * math.sin(2 * math.pi * 5.4 * seconds))
            elif role == "counter_texture":
                value = .75 * math.sin(2 * math.pi * pitch_frequency * seconds)
            elif event["pitch"] == 36:
                value = math.sin(2 * math.pi * (100 - 70 * local) * seconds)
            elif event["pitch"] in (38, 39):
                value = math.sin(2 * math.pi * 190 * seconds) * (1 - local)
            else:
                value = math.sin(2 * math.pi * 6900 * seconds) * (1 - local)
            samples[index] += level * envelope * value

    for role, events in source_events.items():
        for event in events:
            synth(event, role)
    wav = ROOT / "preview" / "footwork-preview-render.wav"
    peak = 0.0
    pcm = array("h")
    for value in samples:
        clipped = max(-.95, min(.95, value))
        peak = max(peak, abs(clipped))
        pcm.extend((int(clipped * 32767), int(clipped * 32767)))
    with wave.open(str(wav), "wb") as output:
        output.setnchannels(2)
        output.setsampwidth(2)
        output.setframerate(rate)
        output.writeframes(pcm.tobytes())
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg missing")
    mp3 = ROOT / "preview" / "footwork-preview.mp3"
    run([ffmpeg, "-y", "-i", str(wav), "-c:a", "libmp3lame", "-b:a", "192k", str(mp3)])
    wav.unlink()
    manifest = {
        "label": "preview, not a master.",
        "preview_path": relative(mp3), "preview_sha256": digest(mp3),
        "source_midi_path": relative(source), "source_midi_sha256": digest(source),
        "renderer": "footwork-simple-synth-Codex 1.0.0",
        "renderer_configuration": {"sample_rate": rate, "source_tracks": sorted(source_events), "processing": "Per-voice synthesis and envelopes; summed samples are clamped to +/-0.95, converted to 16-bit stereo PCM and encoded to 192 kb/s MP3."},
        "selection": {"study": "f01", "start_seconds": 0, "end_seconds": round(duration, 3)},
        "measurement": {"sample_peak": round(peak, 6), "not_lufs_or_true_peak": True},
        "limitations": "Automated generation and decode checks only. Nobody auditioned this preview. Simple synthesis is not evidence of a finished production sound.",
    }
    write_json(ROOT / "preview" / "preview-manifest-Codex.json", manifest)
    return mp3, manifest


def make_art_and_film(audio: Path) -> Path:
    source = ROOT / "art" / "hero-source.png"
    if not source.exists():
        raise RuntimeError("art/hero-source.png missing")
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg missing")
    destinations = [
        (ROOT / "art" / "hero.jpg", "scale=1280:720:force_original_aspect_ratio=increase,crop=1280:720"),
        (ROOT / "art" / "square.jpg", "scale=1080:1080:force_original_aspect_ratio=increase,crop=1080:1080"),
        (ROOT / "social" / "instagram-Codex" / "footwork-square.jpg", "scale=1080:1080:force_original_aspect_ratio=increase,crop=1080:1080"),
        (ROOT / "social" / "instagram-Codex" / "footwork-portrait.jpg", "scale=1080:1350:force_original_aspect_ratio=increase,crop=1080:1350"),
        (ROOT / "social" / "x-Codex" / "footwork-card.jpg", "scale=1080:1080:force_original_aspect_ratio=increase,crop=1080:1080"),
    ]
    for output, filter_graph in destinations:
        run([ffmpeg, "-y", "-i", str(source), "-vf", filter_graph, "-frames:v", "1", "-q:v", "2", str(output)])
    vtt = ROOT / "film" / "footwork-preview.vtt"
    vtt.write_text("WEBVTT\n\n00:00:00.000 --> 00:00:06.500\nFootwork Codex, Cross Grid\npreview, not a master\n\n00:00:06.500 --> 00:00:13.500\nOriginal MIDI study preview\npreview, not a master\n\n00:00:13.500 --> 00:00:20.000\nRendered from the committed MIDI score\npreview, not a master\n", encoding="utf-8")
    film = ROOT / "film" / "footwork-preview.mp4"
    filter_graph = "scale=1280:720,format=yuv420p,drawtext=fontfile='C\\:/Windows/Fonts/arialbd.ttf':text='preview, not a master':fontcolor=white:fontsize=38:box=1:boxcolor=black@0.62:boxborderw=18:x=(w-text_w)/2:y=h-90"
    run([ffmpeg, "-y", "-loop", "1", "-i", str(ROOT / "art" / "hero.jpg"), "-t", "20", "-i", str(audio), "-filter_complex", "[0:v]" + filter_graph + "[v]", "-map", "[v]", "-map", "1:a:0", "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-r", "30", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k", "-t", "20", "-shortest", str(film)])
    write_json(ROOT / "art" / "provenance-Codex.json", {
        "hero_source_path": relative(source), "hero_source_sha256": digest(source), "generator": "built-in image generation",
        "classification": "Original abstract illustration, not a photograph, session record, or evidence that instruments were used.",
        "derived_assets": [relative(path) for path, _ in destinations],
        "prompt_summary": "Staggered rhythm cells on a stable grid with a cobalt waveform. No people, logos, text, or instruments.",
    })
    write_json(ROOT / "film" / "video-manifest-Codex.json", {
        "label": "preview, not a master.", "video_path": relative(film), "video_sha256": digest(film),
        "source_audio_path": relative(audio), "source_audio_sha256": digest(audio),
        "excerpt": {"start_seconds": 0, "end_seconds": 20},
        "encode": {"video": "libx264 CRF 20 at 1280x720 and 30fps", "audio": "AAC 160k", "note": "MP4 audio is re-encoded from MP3 and byte equality is not expected."},
        "poster_path": "art/hero.jpg", "vtt_path": relative(vtt),
    })
    return film


def write_drafts() -> None:
    instagram = "DRAFT. Footwork Codex, Cross Grid, is a 160 BPM original MIDI study built from a steady pulse, displaced drum cells, and a crossing motif. This clip is the generated preview, not a master. Illustration only. #MIDI #musicproduction #composition #synth\n\nAlt text: Abstract dark rhythm grid with red-orange and cream cells plus a blue waveform.\n"
    x_post = "DRAFT: Footwork Codex is a four-study original MIDI collection. Cross Grid previews a 160 BPM score with displaced drum cells over a steady pulse. Preview, not a master. Illustration only. #MIDI #Composition"
    if len(x_post) > 280:
        raise ValueError("X draft exceeds 280 characters")
    (ROOT / "social" / "instagram-Codex" / "caption-Codex.txt").write_text(instagram, encoding="utf-8")
    (ROOT / "social" / "x-Codex" / "post-Codex.txt").write_text(x_post + "\n\nCount: " + str(len(x_post)) + " characters using Python len\n", encoding="utf-8")
    article = """# DRAFT - A four-study MIDI score built around displacement

## Subtitle

Footwork Codex documents four original 160 BPM symbolic studies where short gestures step around a steady pulse.

Tags: MIDI, composition, music production, synthesis, arrangement

The collection is deliberately bounded: 32 bars per study, 4/4 meter, 480 PPQ, six named playback roles, and a visible structural map. Each score has an introduction, statement, contrast, and transformed return. The material is original composition, not a reconstruction of recordings or a claim to represent a scene or community.

The included audio is generated from committed symbolic events with a simple synthesizer. It is a preview, not a master. It demonstrates event timing and source selection, not finished production sound. Automated checks reopened the MIDI and media bytes; nobody auditioned these files.

The catalog links the score, combined files, validation report, audio preview, captioned film, and draft social assets. Use either a combined arrangement or separate part files, never both stacked together.

Call to action: Open the Footwork Codex catalog, inspect the validation record, and download the study archive if the documented limitations fit your workflow.
"""
    (ROOT / "articles" / "medium-draft-Codex.md").write_text(article, encoding="utf-8")
    (ROOT / "articles" / "medium-paste-Codex.txt").write_text("\n".join(line for line in article.splitlines() if not line.startswith("# ")) + "\n", encoding="utf-8")


def write_catalog(all_scores: dict[str, dict[str, list[dict]]], combined: list[Path], archive: Path) -> None:
    data = {
        "pack_identifier": "footwork-codex",
        "display_name": "Footwork Codex",
        "collection": "Original four-study MIDI collection",
        "generator_version": VERSION,
        "seed": None,
        "reproducible_command": "python tools/build_footwork.py",
        "actual_tempo_bpm": BPM,
        "meter": "4/4",
        "ppq": PPQ,
        "end_tick": END_TICK,
        "channels": [{"role": role, "wire_channel": wire, "user_facing_channel": display, "polyphony_cap": cap} for role, _, wire, display, cap in ROLES],
        "studies": [],
        "zip_path": relative(archive),
        "preview_source_selection": {"study": "f01", "combined_file": relative(combined[0]), "start_seconds": 0},
        "limitations": ["Original symbolic material, no samples.", "Automated validation only; nobody auditioned these files.", "Preview is not a master."],
    }
    for study in STUDIES:
        study_data = {
            "id": study["id"], "title": study["title"], "tonic": study["tonic"],
            "pitch_collection": study["collection"], "tempo_bpm": BPM, "meter": "4/4",
            "parts": [{"role": role, "path": "midi/" + study["id"] + "-" + study["slug"] + "/" + role + ".mid", "note_count": len(all_scores[study["id"]][role])} for role, *_ in ROLES],
            "combined_path": "midi/" + study["id"] + "-" + study["slug"] + "/" + study["id"] + "-" + study["slug"] + "-combined.mid",
            "regions": [{"name": label, "start_bar": start + 1, "bars": length} for _, label, start, length in SECTIONS],
        }
        data["studies"].append(study_data)
    write_json(ROOT / "catalog" / "catalog-Codex.json", data)


def write_site_legacy() -> None:
    rows = "\n".join("<tr><td>" + study["id"] + "</td><td>" + study["title"] + "</td><td>" + study["collection"] + "</td><td>160</td><td><a href=\"midi/" + study["id"] + "-" + study["slug"] + "/" + study["id"] + "-" + study["slug"] + "-combined.mid\">combined MIDI</a></td></tr>" for study in STUDIES)
    regions = "\n".join("<li><b>" + label + "</b>, bars " + str(start + 1) + " to " + str(start + length) + ", ticks " + str(start * BAR_TICKS) + " to " + str((start + length) * BAR_TICKS) + "</li>" for _, label, start, length in SECTIONS)
    diagram = """<svg viewBox="0 0 960 150" role="img" aria-labelledby="diagram-title diagram-desc"><title id="diagram-title">Footwork Codex file contract</title><desc id="diagram-desc">Original score events flow to MIDI files and a combined MIDI, then to validation and a simple-synth preview, then to a captioned film and catalog.</desc><style>.b{fill:#161a20;stroke:#e7e0d3;stroke-width:2}.t{fill:#e7e0d3;font:14px system-ui}.a{stroke:#de5e3d;stroke-width:3;marker-end:url(#m)}</style><defs><marker id="m" markerWidth="10" markerHeight="8" refX="8" refY="4" orient="auto"><path d="M0,0 L10,4 L0,8z" fill="#de5e3d"/></marker></defs><rect class="b" x="10" y="45" width="140" height="55" rx="9"/><text class="t" x="29" y="77">score events</text><rect class="b" x="220" y="45" width="150" height="55" rx="9"/><text class="t" x="242" y="69">28 MIDI files</text><text class="t" x="242" y="88">and ZIP</text><rect class="b" x="440" y="45" width="150" height="55" rx="9"/><text class="t" x="460" y="77">read-back validator</text><rect class="b" x="660" y="20" width="135" height="55" rx="9"/><text class="t" x="685" y="52">MP3 preview</text><rect class="b" x="660" y="92" width="135" height="45" rx="9"/><text class="t" x="691" y="120">MP4 and VTT</text><line class="a" x1="150" y1="72" x2="220" y2="72"/><line class="a" x1="370" y1="72" x2="440" y2="72"/><line class="a" x1="590" y1="72" x2="660" y2="47"/><line class="a" x1="590" y1="72" x2="660" y2="114"/></svg>"""
    html = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="description" content="Footwork Codex: four original, documented MIDI studies with validation and a simple-synth preview."><title>Footwork Codex | MIDI Study Pack</title><style>
:root{--ink:#ece5d8;--bg:#12161d;--panel:#1b222c;--accent:#de5e3d;--muted:#aeb8c4}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.55 Inter,ui-sans-serif,system-ui,sans-serif}a{color:#ffd1b9}header,main,footer{width:min(1120px,calc(100% - 2rem));margin:auto}header{padding:42px 0 18px;display:flex;justify-content:space-between;gap:20px;align-items:end}.eyebrow{color:var(--accent);font-size:.78rem;letter-spacing:.13em;text-transform:uppercase}h1{font-size:clamp(2.4rem,7vw,5rem);line-height:.9;margin:.2rem 0 1rem}h2{margin-top:3rem}.lede{font-size:1.15rem;max-width:68ch;color:#d7dce2}.grid{display:grid;grid-template-columns:1.35fr .8fr;gap:22px}.panel{background:var(--panel);border:1px solid #34404d;border-radius:16px;padding:20px}img,video,audio{display:block;width:100%;border-radius:10px}figure{margin:0}figcaption,.small{font-size:.88rem;color:var(--muted)}.badge{display:inline-block;border:1px solid var(--accent);color:#ffd1b9;border-radius:999px;padding:4px 10px;font-size:.82rem}table{width:100%;border-collapse:collapse}th,td{padding:10px 8px;text-align:left;border-bottom:1px solid #34404d}th{color:var(--muted)}code{color:#ffc6ad}.download{display:inline-block;padding:12px 16px;border-radius:8px;background:var(--accent);color:#17110e;font-weight:700;text-decoration:none}.contract svg{width:100%;height:auto;background:#0d1117;border-radius:12px}footer{padding:36px 0 60px;color:var(--muted)}@media(max-width:760px){header,.grid{display:block}.panel{margin:16px 0}header{padding-top:28px}}</style></head><body>
<header><div><p class="eyebrow">Original symbolic composition, 4 studies, 28 MIDI files</p><h1>Footwork Codex</h1><p class="lede">Four original 160 BPM MIDI studies built around rhythmic displacement over a steady grid. This is a file catalog, not a store.</p></div><a class="download" href="downloads/footwork-codex-midi.zip">Download MIDI ZIP</a></header><main>
<section class="grid"><div><figure><img src="art/hero.jpg" width="1280" height="720" alt="Abstract illustration of staggered cream and red-orange rhythm cells on a dark grid, crossed by a cobalt waveform."><figcaption>Illustration, not a recording-session photograph or evidence that instruments were used.</figcaption></figure></div><aside class="panel"><span class="badge">preview, not a master</span><h2>Canonical preview</h2><audio controls preload="metadata"><source src="preview/footwork-preview.mp3" type="audio/mpeg"></audio><p class="small">Rendered from f01 Cross Grid committed combined MIDI with a simple synthesizer. It is not a finished-production claim. <a href="preview/preview-manifest-Codex.json">Source and renderer manifest</a>.</p><h2>Captioned film</h2><video controls preload="metadata" poster="art/hero.jpg"><source src="film/footwork-preview.mp4" type="video/mp4"><track kind="captions" src="film/footwork-preview.vtt" srclang="en" label="English" default></video><p class="small">On-picture and caption disclosure: preview, not a master.</p></aside></section>
<section><h2>What is in the pack</h2><p>Each study is 32 bars in 4/4 at 160 BPM, 480 PPQ, and exactly 61,440 ticks. Five pitched roles use user-facing channels 1 through 5, wire channels 0 through 4; drums use user-facing channel 10, wire channel 9. Bass and principal motif are monophonic. No program changes are encoded. <a href="catalog/patch-recipes-Codex.json">Instrument mapping and renderer recipes</a>.</p><div class="contract">{{DIAGRAM}}</div></section>
<section class="grid"><div class="panel"><h2>Set map</h2><ul>{{REGIONS}}</ul><p class="small">Every study uses this full four-region structure. Exact harmonic and event maps are linked below.</p></div><div class="panel"><h2>Use note</h2><p>Use the combined arrangement or its separate part files. <b>Do not stack the part files on top of the combined file.</b></p><p>Automated validation only; nobody auditioned these files.</p><p><a href="checks/validation-report-Codex.json">Open matched validator report</a></p></div></section>
<section><h2>Studies and combined downloads</h2><div class="panel"><table><thead><tr><th>ID</th><th>Working title</th><th>Collection</th><th>BPM</th><th>File</th></tr></thead><tbody>{{ROWS}}</tbody></table></div></section>
<section class="grid"><div class="panel"><h2>Catalog records</h2><ul><li><a href="catalog/catalog-Codex.json">Catalog JSON</a></li><li><a href="catalog/study-index-Codex.csv">Study index</a></li><li><a href="catalog/note-events-Codex.csv">Canonical note events</a></li><li><a href="catalog/structural-regions-Codex.csv">Structural regions</a></li><li><a href="catalog/harmonic-events-Codex.csv">Harmonic events</a></li><li><a href="catalog/drum-map-Codex.csv">Drum note map</a></li><li><a href="catalog/checksums-Codex.json">File checksums</a></li></ul></div><div class="panel"><h2>Draft publicity</h2><p><a href="articles/medium-draft-Codex.md">DRAFT article</a> and <a href="articles/medium-paste-Codex.txt">plain-text paste</a></p><p><a href="social/instagram-Codex/caption-Codex.txt">DRAFT Instagram caption</a> and <a href="social/x-Codex/post-Codex.txt">DRAFT X post</a></p><p class="small">These drafts are public files in a public repository. They are not posts to Instagram, X, or Medium.</p></div></section>
</main><footer><p>Original study material. No samples, artist endorsements, commercial placements, or cultural-authenticity claims are included. <a href="README-Codex.md">Read build and limitation notes</a> and <a href="delivery-Codex.md">delivery record</a>.</p></footer></body></html>"""
    (ROOT / "index.html").write_text(html.replace("{{ROWS}}", rows).replace("{{REGIONS}}", regions).replace("{{DIAGRAM}}", diagram), encoding="utf-8")
    (ROOT / ".nojekyll").write_text("", encoding="utf-8")


def write_site() -> None:
    template = (ROOT / "docs" / "site-template.html").read_text(encoding="utf-8")
    (ROOT / "index.html").write_text(template, encoding="utf-8")
    (ROOT / ".nojekyll").write_text("", encoding="utf-8")


def write_documents() -> None:
    readme = """# Footwork Codex

Four original note-only MIDI studies for producers who want to pull rhythm apart without losing the grid.

**Live catalog:** https://mizcausevic-dev.github.io/footwork-codex/

This is a documented symbolic-composition release, not a sample pack or a claim to define a genre, its history, or its communities.

## What is here

| Study | Pitch collection | Frame |
| --- | --- | --- |
| f01 Cross Grid | D natural minor | 32 bars · 160 BPM · 4/4 |
| f02 Split Signal | F Dorian | 32 bars · 160 BPM · 4/4 |
| f03 Redline Gap | B Phrygian | 32 bars · 160 BPM · 4/4 |
| f04 Lattice Return | A natural minor | 32 bars · 160 BPM · 4/4 |

The release contains 28 MIDI files: six Format 0 role exports and one Format 1 combined arrangement per study. It also includes the download ZIP, checked CSV/JSON catalogs, patch recipes, an MP3 preview, captioned film, original artwork, and draft public-facing copy.

## Start here

1. Open the [live catalog](https://mizcausevic-dev.github.io/footwork-codex/), or download `downloads/footwork-codex-midi.zip`.
2. Choose either a combined arrangement or its separate part files. **Do not stack both together.**
3. Check `catalog/patch-recipes-Codex.json` for role/channel mapping and `catalog/study-index-Codex.csv` for the compact index.
4. Inspect `checks/validation-report-Codex.json` before relying on a technical claim.

## File contract

- 480 PPQ, 4/4, 160 BPM, 61,440 end ticks per study.
- Five pitched roles use user-facing channels 1–5 (wire channels 0–4); drums use user-facing channel 10 (wire channel 9).
- Bass and principal motif are monophonic; other roles stay within their declared polyphony limits.
- No program changes are encoded. A generic MIDI player may substitute its own default sound for pitched channels and a GM-style drum map on channel 10.
- The source-facing records are in `catalog/`, including note events, harmonic events, structural regions, the drum map, and file checksums.

## Verification boundary

The validator reopens final bytes and checks MIDI parsing, structure, channels, event timing, note pairing, ranges, selected monophonic roles, same-pitch overlap, exact end ticks, CSV agreement, ZIP safety, media decode properties, and a negative overlap fixture.

It does **not** certify groove, melodic quality, commercial suitability, copyright clearance, physical playability, or cultural authenticity. Automated validation passed; nobody auditioned the files.

The MP3 is rendered from committed f01 combined MIDI with a documented simple synthesizer. It is a **preview, not a master**. The MP4 audio is re-encoded from that MP3 and is not expected to match byte-for-byte.

## Build

```powershell
python tools/build_footwork.py
python tools/validate_footwork.py
python -m http.server 4173
```

The deterministic generator writes the MIDI, catalogs, previews, draft copy, static site, and checksum manifest. `docs/site-template.html` is the Pages source template; the generator copies it to `index.html`.

## Repository map

- `midi/` — individual roles and combined arrangements.
- `catalog/` — machine-readable event and integrity records.
- `downloads/` — release ZIP.
- `preview/` and `film/` — derived listening and viewing references.
- `art/` — original abstract visuals and provenance records.
- `docs/site-template.html` — public GitHub Pages template.
- `checks/` — validation output and build metadata.

## Draft materials

The article and social files are drafts only. Their presence in this public repository does not mean they were posted to Medium, Instagram, or X.
"""
    (ROOT / "README.md").write_text(readme, encoding="utf-8")
    delivery = """# Footwork Codex delivery record

## Generated locally

- Repository target: mizcausevic-dev/footwork-codex
- Planned Pages source: main branch, repository root
- Expected live URL after Pages is enabled: https://mizcausevic-dev.github.io/footwork-codex/
- Build state: generated and locally validated; not committed or deployed at the time this file was generated.

## Required post-publish evidence

- Actual commit SHA and remote tree checksum read-back.
- GitHub Pages source and successful deployment.
- Live root page, MP3, MP4, VTT, JPG, ZIP, and MIDI link checks.

## Limitations

Automated validation only; nobody auditioned the files. The preview is not a master.
"""
    if not (ROOT / "delivery-Codex.md").exists():
        (ROOT / "delivery-Codex.md").write_text(delivery, encoding="utf-8")


def write_metadata() -> None:
    ffmpeg = subprocess.run([shutil.which("ffmpeg") or "ffmpeg", "-version"], capture_output=True, text=True).stdout.splitlines()[0]
    ffprobe = subprocess.run([shutil.which("ffprobe") or "ffprobe", "-version"], capture_output=True, text=True).stdout.splitlines()[0]
    write_json(ROOT / "checks" / "build-metadata-Codex.json", {
        "generator_version": VERSION, "source_revision_sha256": digest(Path(__file__)),
        "commands": ["python tools/build_footwork.py", "python tools/validate_footwork.py"],
        "tool_versions": {"python": sys.version.split()[0], "ffmpeg": ffmpeg, "ffprobe": ffprobe},
        "seed": None, "run_time_utc": datetime.now(timezone.utc).isoformat(),
    })


def write_checksums() -> None:
    records = []
    for path in sorted(ROOT.rglob("*")):
        if path.is_file() and ".git" not in path.parts and "__pycache__" not in path.parts and not path.name.startswith("server") and relative(path) not in ("catalog/checksums-Codex.json", "checks/validation-report-Codex.json"):
            records.append({"path": relative(path), "bytes": path.stat().st_size, "sha256": digest(path)})
    write_json(ROOT / "catalog" / "checksums-Codex.json", {"algorithm": "SHA-256", "files": records})


def main() -> int:
    for name in ["midi", "preview", "film", "art", "social/instagram-Codex", "social/x-Codex", "articles", "catalog", "checks/fixtures", "downloads", "docs"]:
        (ROOT / name).mkdir(parents=True, exist_ok=True)
    all_scores, parts, combined = {}, [], []
    for index, study in enumerate(STUDIES):
        score = compose(study, index)
        assert_score(score)
        all_scores[study["id"]] = score
        files, combined_file = write_midi(study, score)
        parts.extend(files)
        combined.append(combined_file)
    write_catalog_csvs(all_scores)
    archive = make_zip(parts, combined)
    audio, _ = render_preview(combined[0])
    film = make_art_and_film(audio)
    write_catalog(all_scores, combined, archive)
    write_drafts()
    write_site()
    write_documents()
    write_metadata()
    (ROOT / "catalog" / "checksums-Codex.json").unlink(missing_ok=True)
    run([sys.executable, str(ROOT / "tools" / "validate_footwork.py"), "--root", str(ROOT)])
    write_checksums()
    run([sys.executable, str(ROOT / "tools" / "validate_footwork.py"), "--root", str(ROOT)])
    print(json.dumps({"status": "generated", "midi_files": len(parts) + len(combined), "archive": relative(archive), "preview": relative(audio), "film": relative(film)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
