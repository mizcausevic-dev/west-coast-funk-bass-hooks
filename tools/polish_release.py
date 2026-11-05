#!/usr/bin/env python3
"""Complete a generated MIDI release with image, film and media receipts."""
from __future__ import annotations
import argparse, hashlib, json, shutil, subprocess, sys
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageOps
import build_release

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def run(args):
    subprocess.run([str(x) for x in args], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)

def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--root',type=Path,required=True); parser.add_argument('--image',type=Path,required=True); parser.add_argument('--art-kind',choices=['ai','programmatic'],default='ai')
    args=parser.parse_args(); root=args.root.resolve(); image=args.image.resolve()
    spec=json.loads((root/'catalog/release-spec.json').read_text(encoding='utf-8'))
    slug=spec['pack_identifier']; title=spec['display_name']; bpm=spec['actual_tempo_bpm']; art_label='AI-generated abstract illustration' if args.art_kind=='ai' else 'Programmatic abstract illustration derived from this release’s original SVG cover'
    art=root/'art'; film=root/'film'; film.mkdir(exist_ok=True)
    source=art/'illustration-source.png'
    if image != source.resolve(): shutil.copy2(image,source)
    base=Image.open(source).convert('RGB')
    hero=ImageOps.fit(base,(1280,720),method=Image.Resampling.LANCZOS); hero.save(art/'hero.jpg',quality=92,optimize=True)
    square=ImageOps.fit(base,(1080,1080),method=Image.Resampling.LANCZOS); square.save(art/'square.jpg',quality=92,optimize=True)
    square.save(root/'social/instagram/square.jpg',quality=90,optimize=True)
    ImageOps.fit(base,(1080,1350),method=Image.Resampling.LANCZOS).save(root/'social/instagram/portrait.jpg',quality=90,optimize=True)
    hero.save(root/'social/x/card.jpg',quality=90,optimize=True)
    poster=hero.copy(); draw=ImageDraw.Draw(poster,'RGBA'); draw.rectangle((0,490,1280,720),fill=(8,12,16,200))
    fontpath=Path('C:/Windows/Fonts/arial.ttf'); boldpath=Path('C:/Windows/Fonts/arialbd.ttf')
    titlefont=ImageFont.truetype(str(boldpath),44); small=ImageFont.truetype(str(fontpath),26)
    draw.text((50,525),title,font=titlefont,fill=(255,255,255,255)); draw.text((52,600),f'{bpm} BPM  /  ORIGINAL MIDI STUDIES',font=small,fill=(255,255,255,255))
    draw.text((52,658),'preview, not master',font=small,fill=(255,255,255,255)); poster.save(film/'poster.jpg',quality=92,optimize=True)
    preview=root/'preview'/f'{slug}-simple-synth-preview.mp3'; video=film/'preview.mp4'
    run(['ffmpeg','-hide_banner','-loglevel','error','-y','-loop','1','-framerate','15','-i',film/'poster.jpg','-i',preview,'-t','18','-vf','scale=1280:720,format=yuv420p','-c:v','libx264','-preset','ultrafast','-c:a','aac','-b:a','128k','-movflags','+faststart','-shortest',video])
    (film/'preview.vtt').write_text('WEBVTT\n\n00:00:00.000 --> 00:00:18.000\nInstrumental MIDI rendering. preview, not master\n',encoding='utf-8',newline='\n')
    probe=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_entries','format=duration:stream=codec_type','-of','json',str(video)],text=True))
    streams={s['codec_type'] for s in probe['streams']}; duration=float(probe['format']['duration'])
    if not {'video','audio'}.issubset(streams) or not 10<=duration<=40: raise ValueError('Invalid film streams or duration')
    (film/'video-manifest.json').write_text(json.dumps({'source_audio':'preview/'+preview.name,'source_audio_sha256':sha(preview),'excerpt_start_seconds':0,'excerpt_duration_seconds':18,'video':'film/preview.mp4','video_sha256':sha(video),'duration_seconds':duration,'video_codec':'H.264','audio_codec':'AAC','caption':'film/preview.vtt','poster':'film/poster.jpg','disclosure':'preview, not master','note':'A static illustrated poster and audio excerpt; no recording-session claim.'},indent=2)+'\n',encoding='utf-8',newline='\n')
    (art/'raster-provenance.json').write_text(json.dumps({'source':'art/illustration-source.png','source_sha256':sha(source),'classification':art_label+', not a recording-session photograph','derived':['art/hero.jpg','art/square.jpg','film/poster.jpg','social/instagram/square.jpg','social/instagram/portrait.jpg','social/x/card.jpg']},indent=2)+'\n',encoding='utf-8',newline='\n')
    draft=(root/'articles/medium-draft.md').read_text(encoding='utf-8'); (root/'articles/medium-paste.txt').write_text(draft,encoding='utf-8',newline='\n')
    caption=f'DRAFT: {title}. Four MIDI studies at {bpm} BPM. Hear the simple-synthesis preview, not a master. #MIDI #MusicProduction #Composition\n\nAlt text: {art_label} for the MIDI collection.\n'; (root/'social/instagram/caption.txt').write_text(caption,encoding='utf-8',newline='\n')
    htmlpath=root/'index.html'; html=htmlpath.read_text(encoding='utf-8'); html=html.replace('src="art/cover.svg"','src="art/hero.jpg"').replace('alt="Original geometric cover with staggered rhythmic cells on a structured grid."',f'alt="{art_label} for this collection."')
    section=f'<section id="film"><p class="eyebrow">Preview film</p><h2>See the study.</h2><video controls preload="metadata" poster="film/poster.jpg" style="width:100%;max-width:900px"><source src="film/preview.mp4" type="video/mp4"><track kind="captions" src="film/preview.vtt" srclang="en" label="English" default></video><p>Illustrated excerpt from the first MIDI study. Preview, not master. Artwork is an illustration.</p><p><a href="film/video-manifest.json">Film provenance</a> · <a href="art/raster-provenance.json">Artwork provenance</a></p></section>'
    if '<section id="studies">' not in html: raise ValueError('Site insertion point missing')
    if 'id="film"' not in html: html=html.replace('<section id="studies">',section+'<section id="studies">',1)
    htmlpath.write_text(html,encoding='utf-8',newline='\n')
    readme=root/'README.md'; content=readme.read_text(encoding='utf-8'); marker='\n## Media\n'
    if marker not in content:
        with readme.open('a',encoding='utf-8',newline='\n') as out: out.write(f'\n## Media\n\nThe 18-second illustrated film uses the first 18 seconds of the canonical MIDI-derived preview. `film/video-manifest.json` records the source hash, excerpt, encoding and caption. Raster art is {art_label.lower()}, not a photograph. Social captions and article are drafts. No human listening review is claimed.\n\nTo regenerate media after rebuilding, preserve the source image and run `python tools/polish_release.py --root . --image art/illustration-source.png --art-kind {args.art_kind}`. Pillow and FFmpeg are required.\n')
    for path,size in [(art/'hero.jpg',(1280,720)),(art/'square.jpg',(1080,1080)),(root/'social/instagram/square.jpg',(1080,1080)),(root/'social/instagram/portrait.jpg',(1080,1350))]:
        with Image.open(path) as im:
            im.verify()
        with Image.open(path) as im:
            if im.size!=size: raise ValueError(f'Wrong dimensions: {path}')
    run(['ffmpeg','-v','error','-i',preview,'-f','null','-']); run(['ffmpeg','-v','error','-i',video,'-f','null','-'])
    (root/'checks/media-validation.json').write_text(json.dumps({'status':'PASS','film_duration_seconds':duration,'streams':sorted(streams),'images':'decoded and dimensions checked','audio':'preview and film decoded with ffmpeg','captions':'single cue covers 0 to 18 seconds','disclosure':'visible on poster for complete static film','limitations':'Automated checks only; no human listening or visual review.'},indent=2)+'\n',encoding='utf-8',newline='\n')
    build_release.write_checksums(root)
    run([sys.executable,root/'tools/validate_release.py','--root',root])
    print(json.dumps({'pack':slug,'status':'PASS','video_seconds':duration}))

if __name__=='__main__': main()
