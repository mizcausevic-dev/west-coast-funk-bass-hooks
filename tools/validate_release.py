#!/usr/bin/env python3
"""Independent read-back validator for profile-driven MIDI release bytes."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import build_footwork as engine


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def add_error(errors: list[str], text: str) -> None:
    if text not in errors:
        errors.append(text)


def overlaps(events: list[dict], mono: bool = False) -> bool:
    latest: dict[int, int] | int = -1 if mono else {}
    for event in sorted(events, key=lambda item: (item["start"], item["pitch"])):
        if mono:
            if event["start"] < latest:
                return True
            latest = event["start"] + event["duration"]
        else:
            by_pitch = latest
            if event["start"] < by_pitch.get(event["pitch"], -1):
                return True
            by_pitch[event["pitch"]] = event["start"] + event["duration"]
    return False


def normalized(events: list[dict]) -> list[tuple[int, int, int, int, int]]:
    return sorted((e["start"], e["duration"], e["pitch"], e["velocity"], e["channel"]) for e in events)


def configure(spec: dict, root: Path) -> None:
    engine.ROOT = root
    engine.BPM = int(spec["actual_tempo_bpm"])
    engine.TEMPO_US = round(60_000_000 / engine.BPM)
    engine.ROLES = [(r["role"], r["role"], r["wire_channel"], r["user_facing_channel"], r["polyphony_cap"]) for r in spec["roles"]]
    engine.ROLE = {item[0]: item for item in engine.ROLES}


def role_folder(root: Path, study: dict) -> Path:
    folder = next((path for path in (root / "midi").glob(study["id"] + "-*") if path.is_dir()), None)
    if folder is None:
        raise FileNotFoundError("study folder missing for " + study["id"])
    return folder


def duplicate_review(studies: list[dict], parsed: dict[Path, dict], root: Path) -> list[dict]:
    signatures: dict[tuple, list[str]] = {}
    for study in studies:
        try:
            folder = role_folder(root, study)
            source = parsed[folder / "principal_motif.mid"]["tracks"][0]["events"]
            first = sorted(source, key=lambda e: (e["start"], e["pitch"]))[:12]
            if not first:
                continue
            origin = first[0]["pitch"]
            signature = tuple((e["start"] - first[0]["start"], e["duration"], e["pitch"] - origin) for e in first)
            signatures.setdefault(signature, []).append(study["id"])
        except (FileNotFoundError, KeyError):
            continue
    return [{"normalized_motif_signature": list(key), "studies": value} for key, value in signatures.items() if len(value) > 1]


def negative_control(root: Path) -> bool:
    fixture = root / "checks" / "fixtures" / "invalid-same-pitch-overlap.mid"
    events = engine.common_meta("negative fixture") + [
        (0, 3, bytes([144, 60, 80])), (240, 3, bytes([144, 60, 80])),
        (720, 2, bytes([128, 60, 0])), (720, 2, bytes([128, 60, 0])),
    ]
    fixture.write_bytes(engine.midi(0, [engine.track(events)]))
    parsed = engine.parse_midi(fixture)
    return overlaps(parsed["tracks"][0]["events"])


def validate(root: Path) -> dict:
    errors: list[str] = []
    warnings: list[str] = []
    spec_path = root / "catalog" / "release-spec.json"
    try:
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"status": "FAIL", "errors": ["release spec error: " + str(exc)], "warnings": [], "files_checked": 0}
    configure(spec, root)
    roles = [item["role"] for item in spec["roles"]]
    studies = spec["studies"]
    midi_files = sorted((root / "midi").rglob("*.mid"))
    if len(midi_files) != 28:
        add_error(errors, f"expected 28 MIDI files, found {len(midi_files)}")
    combined = [path for path in midi_files if path.name.endswith("-combined.mid")]
    role_files = [path for path in midi_files if path.stem in roles]
    if len(combined) != 4 or len(role_files) != 24:
        add_error(errors, "MIDI export count does not match four combined and 24 role files")
    parsed: dict[Path, dict] = {}
    records = []
    for path in midi_files:
        record = {"path": path.relative_to(root).as_posix(), "bytes": path.stat().st_size, "sha256": digest(path), "errors": []}
        try:
            value = engine.parse_midi(path); parsed[path] = value
            expected_format = 1 if path.name.endswith("-combined.mid") else 0
            if value["format"] != expected_format: record["errors"].append("format")
            if value["division"] != 480: record["errors"].append("ppq")
            all_events = [event for track in value["tracks"] for event in track["events"]]
            if not all_events: record["errors"].append("zero_notes")
            metas = [item for track in value["tracks"] for item in track["metas"]]
            if not any(kind == 81 and int.from_bytes(body, "big") == engine.TEMPO_US for _, kind, body in metas): record["errors"].append("tempo")
            if not any(kind == 88 and body == bytes([4, 2, 24, 8]) for _, kind, body in metas): record["errors"].append("meter")
            for track in value["tracks"]:
                if track["eot"] != 61440: record["errors"].append("end_tick")
                if track["forbidden"]: record["errors"].append("forbidden_messages")
                if overlaps(track["events"]): record["errors"].append("same_pitch_overlap")
                for event in track["events"]:
                    if event["duration"] <= 0 or event["start"] < 0 or event["start"] + event["duration"] > 61440: record["errors"].append("event_timing")
                    if not 0 <= event["pitch"] <= 127 or not 1 <= event["velocity"] <= 127: record["errors"].append("note_range")
            if expected_format == 0:
                role = path.stem; track = value["tracks"][0]
                expected_channel = engine.ROLE[role][2]
                if {event["channel"] for event in track["events"]} != {expected_channel}: record["errors"].append("channel")
                if role in ("sub_bass", "principal_motif") and overlaps(track["events"], mono=True): record["errors"].append("monophonic_role")
            else:
                names = [track["name"] for track in value["tracks"]]
                if not all(role in names for role in roles): record["errors"].append("combined_track_names")
        except Exception as exc:
            record["errors"].append("parse: " + str(exc))
        if record["errors"]:
            add_error(errors, record["path"] + ": " + ", ".join(sorted(set(record["errors"]))))
        records.append(record)
    for study in studies:
        try:
            folder = role_folder(root, study); combined_path = next(folder.glob("*-combined.mid"))
            tracks = {track["name"]: track["events"] for track in parsed[combined_path]["tracks"]}
            for role in roles:
                single = folder / (role + ".mid")
                if single not in parsed or role not in tracks:
                    add_error(errors, study["id"] + " missing comparison source for " + role)
                elif normalized(parsed[single]["tracks"][0]["events"]) != normalized(tracks[role]):
                    add_error(errors, study["id"] + " combined events disagree with " + role)
        except Exception as exc:
            add_error(errors, study["id"] + " combined comparison error: " + str(exc))
    try:
        csv_events: dict[tuple[str, str], list[tuple[int, int, int, int, int]]] = {}
        with (root / "catalog" / "note-events.csv").open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                csv_events.setdefault((row["study_id"], row["role"]), []).append((int(row["start_tick"]), int(row["duration_tick"]), int(row["pitch"]), int(row["velocity"]), int(row["user_facing_channel"]) - 1))
        for study in studies:
            folder = role_folder(root, study)
            for role in roles:
                expected = normalized(parsed[folder / (role + ".mid")]["tracks"][0]["events"])
                if expected != sorted(csv_events.get((study["id"], role), [])):
                    add_error(errors, "CSV event mismatch for " + study["id"] + " " + role)
    except Exception as exc:
        add_error(errors, "canonical note CSV error: " + str(exc))
    try:
        groups: dict[str, list[dict]] = {}
        with (root / "catalog" / "structural-regions.csv").open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle): groups.setdefault(row["study_id"], []).append(row)
        for study in studies:
            rows = sorted(groups.get(study["id"], []), key=lambda row: int(row["start_tick"])); prior = 0
            if len(rows) != 4: add_error(errors, "region count for " + study["id"]); continue
            for row in rows:
                start, end = int(row["start_tick"]), int(row["end_tick"])
                if start != prior or end <= start: add_error(errors, "region coverage gap or overlap for " + study["id"])
                prior = end
            if prior != 61440: add_error(errors, "region coverage end for " + study["id"])
    except Exception as exc:
        add_error(errors, "region CSV error: " + str(exc))
    try:
        mapped = {36, 38, 39, 42, 46}; used = set()
        for study in studies:
            used.update(event["pitch"] for event in parsed[role_folder(root, study) / "drums.mid"]["tracks"][0]["events"])
        if used != mapped: add_error(errors, "drum map does not exactly cover actual drum events")
    except Exception as exc:
        add_error(errors, "drum map error: " + str(exc))
    archive = root / "downloads" / f"{spec['pack_identifier']}-midi.zip"
    try:
        with zipfile.ZipFile(archive) as package:
            names = package.namelist()
            if any(name.startswith("/") or ".." in Path(name).parts or "\\" in name for name in names): add_error(errors, "ZIP has unsafe member path")
            if not {path.relative_to(root).as_posix() for path in midi_files}.issubset(set(names)): add_error(errors, "ZIP is missing MIDI members")
            for name in names:
                if name.endswith(".mid"):
                    temporary = root / "checks" / "fixtures" / ("zip-" + Path(name).name)
                    temporary.write_bytes(package.read(name)); engine.parse_midi(temporary); temporary.unlink()
    except Exception as exc:
        add_error(errors, "ZIP validation error: " + str(exc))
    preview = root / "preview" / f"{spec['pack_identifier']}-simple-synth-preview.mp3"
    try:
        probe = engine.probe(preview)
        if not any(stream.get("codec_type") == "audio" for stream in probe.get("streams", [])): add_error(errors, "preview has no audio stream")
    except Exception as exc:
        add_error(errors, "preview decode error: " + str(exc))
    try:
        manifest = json.loads((root / "preview" / "preview-manifest.json").read_text(encoding="utf-8"))
        if digest(root / manifest["source_midi_path"]) != manifest["source_midi_sha256"] or digest(root / manifest["preview_path"]) != manifest["preview_sha256"]: add_error(errors, "preview provenance hash")
    except Exception as exc:
        add_error(errors, "preview provenance error: " + str(exc))
    checksum = root / "catalog" / "checksums.json"
    if checksum.exists():
        try:
            for row in json.loads(checksum.read_text(encoding="utf-8"))["files"]:
                path = root / row["path"]
                if not path.exists() or path.stat().st_size != row["bytes"] or digest(path) != row["sha256"]: add_error(errors, "checksum mismatch " + row["path"])
        except Exception as exc:
            add_error(errors, "checksum manifest error: " + str(exc))
    else:
        warnings.append("checksum manifest absent on initial validation pass")
    if not negative_control(root): add_error(errors, "negative same-pitch-overlap control did not fail as expected")
    duplicates = duplicate_review(studies, parsed, root)
    if duplicates: warnings.append("transposition-normalized principal motif duplicate flagged for human review")
    return {"status": "PASS" if not errors else "FAIL", "run_time_utc": datetime.now(timezone.utc).isoformat(), "tool": "validate_release.py with Python " + sys.version.split()[0], "files_checked": len(midi_files), "errors": errors, "warnings": warnings, "midi_files": records, "duplicate_review": duplicates, "negative_control": {"path": "checks/fixtures/invalid-same-pitch-overlap.mid", "expected_result": "rejected for same-pitch overlap", "passed": not errors or "negative same-pitch-overlap control did not fail as expected" not in errors}, "limitations": ["Automated technical validation only.", "Nobody auditioned these files.", "Duplicate-motif review is bounded and not exhaustive copyright clearance."]}


def main() -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1]); args = parser.parse_args(); root = args.root.resolve()
    report = validate(root); target = root / "checks" / "validation-report.json"; target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes((json.dumps(report, indent=2) + "\n").encode("utf-8"))
    print(json.dumps({"status": report["status"], "errors": len(report["errors"]), "warnings": len(report["warnings"]), "report": target.relative_to(root).as_posix()}, indent=2)); return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
