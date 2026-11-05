#!/usr/bin/env python3
"""Render a moving MIDI-note visualizer from a release's documented preview."""
import argparse
import csv
import hashlib
import json
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

W,H,FPS,DURATION = 960,540,15,18
COLORS = {"chord_pulse":"#f3b267","sub_bass":"#ec7063","principal_motif":"#80d7de","vocal_like_synth":"#b7a1ed","counter_texture":"#b4d18a","drums":"#f2e5ce"}
def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()
def run(command,cwd=None):
    return subprocess.run([str(x) for x in command],cwd=cwd,check=True,capture_output=True,text=True)
def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--root",type=Path,required=True)
    parser.add_argument("--art",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--name",required=True)
    parser.add_argument("--bpm",type=int,required=True)
    parser.add_argument("--study",required=True)
    args=parser.parse_args()
    root=args.root.resolve()
    art=args.art.resolve()
    out=args.output.resolve()
    out.mkdir(parents=True,exist_ok=True)
    preview_path=root/"preview"/("preview-manifest-Codex.json" if (root/"preview"/"preview-manifest-Codex.json").exists() else "preview-manifest.json")
    preview=json.loads(preview_path.read_text(encoding="utf-8"))
    audio=root/preview["preview_path"]
    midi=root/preview["source_midi_path"]
    if sha(audio)!=preview["preview_sha256"] or sha(midi)!=preview["source_midi_sha256"]:
        raise ValueError("Preview source hashes do not match the existing manifest")
    if preview["selection"]["study"]!=args.study or float(preview["selection"]["start_seconds"])!=0:
        raise ValueError("Unrecognized preview selection")
    csvpath=root/"catalog"/("note-events-Codex.csv" if (root/"catalog"/"note-events-Codex.csv").exists() else "note-events.csv")
    notes=[]
    with csvpath.open(encoding="utf-8",newline="") as handle:
        for row in csv.DictReader(handle):
            if row["study_id"]!=args.study: continue
            start=int(row["start_tick"])*60/(args.bpm*480)
            end=(int(row["start_tick"])+int(row["duration_tick"]))*60/(args.bpm*480)
            if start<DURATION and end>0:
                notes.append((start,end,row["role"],int(row["pitch"])))
    if not notes: raise ValueError("No MIDI events in selected interval")
    # Note rectangles are placed in time coordinates, then move past a fixed playhead.
    scale=76
    roll=Image.new("RGBA",(DURATION*scale+W,152),(0,0,0,0))
    draw=ImageDraw.Draw(roll)
    roles=list(COLORS)
    for start,end,role,pitch in notes:
        if role not in COLORS: continue
        lane=roles.index(role)
        y=8+lane*23
        x=int(start*scale)
        draw.rounded_rectangle((x,y,max(x+3,int(min(end,DURATION)*scale)),y+10),radius=4,fill=COLORS[role])
    roll.save(out/"motion-note-roll.png")
    panel=Image.new("RGBA",(W,H),(0,0,0,0))
    d=ImageDraw.Draw(panel)
    regular=ImageFont.truetype("C:/Windows/Fonts/arial.ttf",18)
    small=ImageFont.truetype("C:/Windows/Fonts/arial.ttf",15)
    big=ImageFont.truetype("C:/Windows/Fonts/arialbd.ttf",43)
    d.rectangle((0,0,W,190),fill=(9,14,19,165))
    d.rectangle((0,265,W,H),fill=(9,14,19,192))
    d.text((46,28),"ORIGINAL MIDI  /  MOTION PREVIEW",font=small,fill=(216,226,228,255))
    title=args.name
    while d.textbbox((0,0),title,font=big)[2]>W-92 and big.size>25:
        big=ImageFont.truetype("C:/Windows/Fonts/arialbd.ttf",big.size-2)
    d.text((44,66),title,font=big,fill=(255,255,255,255))
    d.text((47,130),f"{args.bpm} BPM   ·   {args.study.upper()}   ·   MIDI-DRIVEN NOTE VIEW",font=regular,fill=(225,232,232,255))
    d.text((47,276),"NOTES FROM THE PREVIEW SCORE",font=small,fill=(225,232,232,255))
    d.line((47,303,47,448),fill=(255,255,255,230),width=2)
    for i,role in enumerate(roles):
        x=47+i*145
        d.ellipse((x,169,x+8,177),fill=COLORS[role])
        label={"chord_pulse":"CHORDS","sub_bass":"BASS","principal_motif":"MELODY","vocal_like_synth":"VOICE","counter_texture":"TEXTURE","drums":"DRUMS"}[role]
        d.text((x+14,165),label,font=small,fill=(235,239,239,255))
    d.rectangle((0,460,W,H),fill=(6,9,12,215))
    d.text((47,483),"preview, not master",font=regular,fill=(255,255,255,255))
    d.text((47,512),"Simple-synth MIDI rendering  ·  Not a recorded performance",font=small,fill=(197,209,210,255))
    panel.save(out/"motion-overlay.png")
    video=out/"motion-preview.mp4"
    graph=("[0:v]scale=1040:586,crop=960:540:x='40+18*sin(t*0.22)':y='23+10*cos(t*0.20)',setsar=1[bg];"
           "[bg][2:v]overlay=0:0:shortest=1[panel];"
           "[panel][1:v]overlay=x='47-76*t':y=303:shortest=1,format=yuv420p[v]")
    run(["ffmpeg","-hide_banner","-loglevel","error","-y","-loop","1","-framerate",str(FPS),"-i",art,
         "-loop","1","-framerate",str(FPS),"-i",out/"motion-note-roll.png",
         "-loop","1","-framerate",str(FPS),"-i",out/"motion-overlay.png","-i",audio,
         "-filter_complex",graph,"-map","[v]","-map","3:a:0","-t",str(DURATION),
         "-c:v","libx264","-preset","veryfast","-crf","22","-c:a","aac","-b:a","160k","-movflags","+faststart",video])
    (out/"motion-preview.vtt").write_text("WEBVTT\n\n00:00:00.000 --> 00:00:18.000\nInstrumental MIDI preview; preview, not master.\n",encoding="utf-8",newline="\n")
    probe=json.loads(run(["ffprobe","-v","error","-show_entries","format=duration:stream=codec_type,width,height","-of","json",video]).stdout)
    duration=float(probe["format"]["duration"])
    streams={s["codec_type"] for s in probe["streams"]}
    frames=run(["ffmpeg","-v","error","-i",video,"-an","-vf","select=eq(n\\,0)+eq(n\\,150)","-vsync","0","-f","framemd5","-"]).stdout
    frame_hashes=[line.split(",")[-1].strip() for line in frames.splitlines() if line and not line.startswith("#")]
    if not {"video","audio"}.issubset(streams) or not 17.9<=duration<=18.1 or len(frame_hashes)!=2 or frame_hashes[0]==frame_hashes[1]:
        raise ValueError("Motion, duration, or stream verification failed")
    manifest={"title":args.name,"study":args.study,"bpm":args.bpm,"source_audio":preview["preview_path"],"source_audio_sha256":sha(audio),"source_midi":preview["source_midi_path"],"source_midi_sha256":sha(midi),"source_events":csvpath.relative_to(root).as_posix(),"source_events_sha256":sha(csvpath),"art_source_file":art.name,"art_source_sha256":sha(art),"excerpt_start_seconds":0,"duration_seconds":duration,"video":"film/motion-preview.mp4","video_sha256":sha(video),"caption":"film/motion-preview.vtt","resolution":"960x540","fps":FPS,"visualization":"Scrolling note events from the selected score over a moving cover image","disclosure":"preview, not master","limitations":["Simple-synth rendering, not a recorded performance.","No human listening review recorded."]}
    (out/"motion-manifest.json").write_text(json.dumps(manifest,indent=2)+"\n",encoding="utf-8",newline="\n")
    print(json.dumps({"name":args.name,"events":len(notes),"duration":duration,"motion":True,"status":"PASS"}))

if __name__=="__main__":
    main()
