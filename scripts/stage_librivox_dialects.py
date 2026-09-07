#!/usr/bin/env python3
"""
stage_librivox_dialects.py — build Chatterbox reference clips from the LibriVox
"Dialect and Accent" collections.

WHY THIS SOURCE: it is the only free corpus I could find where English speakers
are explicitly labelled **by US region** (Texas metro, North Texas, NYC, Upstate
NY, South Carolina, South Louisiana, Minnesota, Great Lakes, Kansas, Pacific NW,
SE Pennsylvania, W. Central PA, Southern Indiana, SoCal, Midwestern x3, ...) and
the recordings are in the **public domain** — no attribution required, safe to
redistribute in an open repo or a voice marketplace.

  Vol 1: https://archive.org/details/dialect_accent_0909_librivox   (PD)
  Vol 2: https://archive.org/details/celebration_dialects_accents_vol2_1312_librivox  (PD Mark 1.0)
  LibriVox PD policy: https://librivox.org/pages/public-domain/

Each track is one reader reading the same short passage, ~50-85 s, with a spoken
LibriVox intro at the head and a credit at the tail. This script finds the main
body automatically (RMS segmentation), cuts a ~15 s window from it, loudness-
normalises it, and writes a mono WAV plus a MANIFEST.json carrying region,
reader, licence and a rough quality score.

DEPENDENCIES: ffmpeg + ffprobe on PATH. Nothing else — pure stdlib otherwise.
  macOS:  brew install ffmpeg

RECOMMENDED FLOW (mirrors scripts/stage_vctk_voices.py):
  1) Pull + audition:   python3 scripts/stage_librivox_dialects.py --region us
  2) Listen to librivox_voices/*.wav, delete the ones you don't like.
     Rename survivors NOW if you want different names (see the warning below).
  3) Upload keepers:    python3 scripts/stage_librivox_dialects.py \
                            --from-dir librivox_voices \
                            --upload-to http://GIDEON_HOST:8101

⚠️  Filenames on the Chatterbox box are PERMANENT — AnimaForge and every
    voice_map.json reference them by filename. Rename before upload, never after.
"""

import argparse
import array
import json
import math
import os
import re
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

# ── Sources ───────────────────────────────────────────────────────────────────

ITEMS = [
    ("vol1", "dialect_accent_0909_librivox",
     "https://archive.org/details/dialect_accent_0909_librivox"),
    ("vol2", "celebration_dialects_accents_vol2_1312_librivox",
     "https://archive.org/details/celebration_dialects_accents_vol2_1312_librivox"),
]

LICENSE = {
    "spdx": "CC0-1.0",
    "label": "Public domain (LibriVox)",
    "distributable": True,
    "attribution_required": False,
    "note": ("LibriVox recordings are dedicated to the public domain; the project's own "
             "policy states no credit is required. https://librivox.org/pages/public-domain/"),
}

# Title fragments that mean "this reader is American". Order matters: the first
# match supplies the region slug.
US_REGIONS = [
    (r"Metropolitan Texas", "texas-metro"),
    (r"North Texas", "texas-north"),
    (r"\bTexas\b", "texas"),
    (r"New York City", "nyc"),
    (r"Upstate New York", "newyork-upstate"),
    (r"South Carolina", "southcarolina"),
    (r"South(ern)? Louisiana", "louisiana-south"),
    (r"Southeastern Pennsylvania", "pennsylvania-se"),
    (r"West Central Pennsylvania", "pennsylvania-wc"),
    (r"Southern Indiana", "indiana-south"),
    (r"Southern California", "socal"),
    (r"Pacific Northwest", "pacificnw"),
    (r"Great Lakes", "greatlakes"),
    (r"Kansas", "kansas"),
    (r"Minnesota", "minnesota"),
    (r"Midwest(ern)?", "midwest"),
    (r"Air Force Brat", "military-brat"),
    (r"American accent, western", "west"),
    (r"\bAmerican\b", "american"),
    (r"\bUS(A)?\b", "american"),
]

# Non-US labels, kept for --region all. Slug = lowercased first word or two.
NONUS_HINTS = [
    (r"Newfoundland", "newfoundland"), (r"Canadian", "canadian"),
    (r"Lancashire", "lancashire"), (r"Black Country", "blackcountry"),
    (r"South-East London", "london-se"), (r"Received Pronunciation|Public School", "rp"),
    (r"Mid-England", "england-mid"), (r"Mid-Atlantic British", "midatlantic"),
    (r"English accent", "english"), (r"Scottish", "scots"), (r"Irish", "irish"),
    (r"Australian", "australian"), (r"New Zealand", "newzealand"),
    (r"German", "german"), (r"Austrian", "austrian"), (r"Dutch", "dutch"),
    (r"Flemish", "flemish"), (r"Hungarian", "hungarian"),
    (r"Chinese accent, Taiwan", "taiwan"), (r"Singaporean", "singapore"),
    (r"Chinese", "chinese"), (r"Indian", "indian"), (r"French", "french"),
    (r"Spanish", "spanish"), (r"Italian", "italian"), (r"Russian", "russian"),
]

TRACK_RE = re.compile(r"^\s*\d+\s*-\s*")          # vol2 titles are "07 - Foo accent"
READER_RE = re.compile(r"^read by\s+", re.I)


# ── ffmpeg helpers ────────────────────────────────────────────────────────────

def need_ffmpeg():
    missing = [b for b in ("ffmpeg", "ffprobe") if not shutil.which(b)]
    if missing:
        sys.exit(f"ERROR: {' and '.join(missing)} not found on PATH.\n"
                 f"  macOS:  brew install ffmpeg\n"
                 f"  Debian: sudo apt install ffmpeg")


def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def decode_pcm(path, sr=16000):
    """Decode any input to mono 16-bit PCM at `sr` and return an array('h')."""
    p = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-ac", "1", "-ar", str(sr),
         "-f", "s16le", "-"],
        capture_output=True)
    a = array.array("h")
    a.frombytes(p.stdout)
    return a, sr


# ── Analysis (stdlib only) ────────────────────────────────────────────────────

def rms_windows(pcm, sr, win=0.25):
    """Per-window RMS in dBFS."""
    n = max(1, int(sr * win))
    out = []
    for i in range(0, len(pcm) - n + 1, n):
        s = 0
        for x in pcm[i:i + n]:
            s += x * x
        r = math.sqrt(s / n) + 1e-9
        out.append(20 * math.log10(r / 32768.0))
    return out, win


def speech_runs(db, win, thr, gap_sec=1.2):
    """Contiguous above-threshold runs, joined across gaps of <= gap_sec."""
    gap_win = int(gap_sec / win)
    runs, cur, gap = [], None, 0
    for i, v in enumerate(db):
        if v >= thr:
            if cur is None:
                cur = i
            gap = 0
        elif cur is not None:
            gap += 1
            if gap > gap_win:
                runs.append((cur, i - gap))
                cur, gap = None, 0
    if cur is not None:
        runs.append((cur, len(db) - 1))
    return [(a, b) for a, b in runs if (b - a) * win >= 2.0]


def find_body(pcm, sr, intro_guard=16.0, tail_guard=3.0):
    """Locate the passage body, skipping the spoken LibriVox intro and end credit.

    Every track in these collections opens with the reader speaking the LibriVox
    boilerplate ("This is a LibriVox recording…") and closes with a credit. The
    boilerplate is the same words in every clip and is often delivered flatter
    than the passage, so it makes a worse reference — but it is NOT reliably
    separated by a pause (some readers run straight on). So we combine two
    signals: drop any speech run that ends before `intro_guard`, and hard-clamp
    the start to `intro_guard` regardless. 16 s clears every intro in both
    volumes with room to spare.
    """
    dur = len(pcm) / sr
    db, win = rms_windows(pcm, sr)
    if not db:
        return 0.0, dur
    loud = sorted(db)[int(len(db) * 0.9)]          # 90th percentile = speech level
    thr = loud - 18.0                              # 18 dB below speech = silence
    runs = speech_runs(db, win, thr)
    if not runs:
        return min(intro_guard, max(0.0, dur - 5)), dur

    kept = [(a, b) for a, b in runs if (b + 1) * win > intro_guard]
    if not kept:                                   # unusually short track
        kept = runs
    # A short final run is the end credit, not passage material.
    if len(kept) > 1 and (kept[-1][1] - kept[-1][0]) * win < 6.0:
        kept = kept[:-1]

    start = max(kept[0][0] * win, intro_guard)
    end = min((kept[-1][1] + 1) * win, dur - tail_guard)
    if end - start < 4.0:                          # guard collapsed the window
        start, end = max(0.0, intro_guard), dur
    return start, end


def pick_window(pcm, sr, body, seconds):
    """Choose the `seconds`-long window inside `body` with the most speech and
    the fewest dead spots — and start it a beat after the body begins so we do
    not open on a breath."""
    db, win = rms_windows(pcm, sr)
    b0, b1 = body
    if b1 - b0 <= seconds:
        return max(0.0, b0), min(b1, b0 + seconds)
    loud = sorted(db)[int(len(db) * 0.9)]
    thr = loud - 18.0
    n = int(seconds / win)
    lo = int((b0 + 0.4) / win)
    hi = int(b1 / win) - n
    best, best_score = lo, -1e9
    for s in range(lo, max(lo + 1, hi + 1)):
        seg = db[s:s + n]
        if not seg:
            continue
        voiced = sum(1 for v in seg if v >= thr) / len(seg)
        mean = sum(seg) / len(seg)
        # start on a quiet window = a natural pause, not mid-word
        onset = -2.0 if db[s] < thr else 0.0
        score = voiced * 40 + mean + onset
        if score > best_score:
            best, best_score = s, score
    return best * win, best * win + seconds


def estimate_f0(path):
    """Median voiced F0 via autocorrelation. Used only for a gender *guess*.

    Runs on an 8 kHz decode — plenty for a 60-320 Hz search, and ~20x faster
    than doing it at 16 kHz in pure Python.
    """
    pcm, sr = decode_pcm(path, 8000)
    lo, hi = int(sr / 320), int(sr / 60)           # 60-320 Hz search range
    frame, hop = int(sr * 0.04), int(sr * 0.06)
    vals = []
    for i in range(0, len(pcm) - frame, hop):
        w = pcm[i:i + frame]
        energy = sum(x * x for x in w) / frame
        if energy < 1_000_000:                     # skip near-silence
            continue
        best_lag, best_corr, zero = 0, 0.0, float(energy * frame)
        if zero <= 0:
            continue
        for lag in range(lo, hi):
            c = 0
            for j in range(0, frame - lag, 2):     # stride 2: 2x faster, same peak
                c += w[j] * w[j + lag]
            c = c * 2 / zero
            if c > best_corr:
                best_corr, best_lag = c, lag
        if best_lag and best_corr > 0.30:
            vals.append(sr / best_lag)
    if len(vals) < 8:
        return None, ""
    vals.sort()
    f0 = vals[len(vals) // 2]
    # Deliberately conservative: the 165-185 Hz overlap band gets no guess.
    g = "m" if f0 < 165 else "f" if f0 > 185 else ""
    return round(f0, 1), g


def noise_floor(pcm, sr):
    """Room-noise level, measured on the FULL source track.

    It has to come from the source, not the clip: a good 15 s reference clip is
    wall-to-wall speech and therefore contains no silence to measure. Measuring
    the clip alone scores the cleanest recordings *worst*, which is exactly
    backwards.
    """
    db, _ = rms_windows(pcm, sr)
    if not db:
        return -90.0
    return sorted(db)[max(0, int(len(db) * 0.05))]


def quality(pcm, sr, floor):
    """Rough 0-100 listen-first score: SNR, minus clipping, minus dead air."""
    db, win = rms_windows(pcm, sr)
    if not db:
        return 0, {}
    db_s = sorted(db)
    speech = db_s[int(len(db_s) * 0.9)]
    snr = speech - floor
    clip = sum(1 for x in pcm if abs(x) >= 32700) / max(1, len(pcm))
    dead = sum(1 for v in db if v < speech - 25) / len(db)   # silence inside the clip
    score = int((snr - 12) * 2.4) - int(clip * 5000) - int(dead * 60)
    return max(0, min(100, score)), {
        "speech_dbfs": round(speech, 1),
        "noise_floor_dbfs": round(floor, 1),
        "snr_db": round(snr, 1),
        "clipping_pct": round(clip * 100, 3),
        "dead_air_pct": round(dead * 100, 1),
    }


# ── Catalogue ─────────────────────────────────────────────────────────────────

def slug_for(title):
    for pat, slug in US_REGIONS:
        if re.search(pat, title, re.I):
            return slug, True
    for pat, slug in NONUS_HINTS:
        if re.search(pat, title, re.I):
            return slug, False
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:20] or "unknown", False


def fetch_catalogue(cache: Path):
    tracks = []
    for vol, ident, page in ITEMS:
        meta_path = cache / f"{ident}.json"
        if not meta_path.exists():
            urllib.request.urlretrieve(f"https://archive.org/metadata/{ident}", meta_path)
        d = json.loads(meta_path.read_text(encoding="utf-8"))
        for f in d.get("files", []):
            if f.get("format") != "VBR MP3":
                continue
            title = TRACK_RE.sub("", f.get("title") or "").strip()
            reader = READER_RE.sub("", (f.get("artist") or "")).strip()
            if not reader:
                m = re.search(r"_([a-z0-9]+)\.mp3$", f["name"])
                reader = m.group(1) if m else "unknown"
            region, is_us = slug_for(title)
            tracks.append({
                "vol": vol, "item": ident, "page": page, "file": f["name"],
                "url": f"https://archive.org/download/{ident}/{f['name']}",
                "label": title, "reader": reader, "region": region, "us": is_us,
                "source_seconds": float(f.get("length") or 0) if str(f.get("length") or "").replace(".", "").isdigit() else None,
            })
    return tracks


# ── Pull ──────────────────────────────────────────────────────────────────────

def do_pull(args):
    need_ffmpeg()
    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)
    cache = Path(args.cache); cache.mkdir(parents=True, exist_ok=True)

    tracks = fetch_catalogue(cache)
    if args.region == "us":
        tracks = [t for t in tracks if t["us"]]
    elif args.region != "all":
        tracks = [t for t in tracks if t["region"] == args.region]
    if not tracks:
        sys.exit(f"No tracks matched --region {args.region}")

    resume_index = {}
    mf = out / "MANIFEST.json"
    if mf.exists() and not args.force:
        try:
            resume_index = {m["filename"]: m for m in json.loads(mf.read_text(encoding="utf-8"))}
        except (OSError, json.JSONDecodeError):
            resume_index = {}

    print(f"{len(tracks)} track(s) to stage → {out}/\n")
    manifest = []
    seen = {}
    for i, t in enumerate(tracks, 1):
        # Name first: it depends only on the catalogue, so a resumed run can
        # skip a track without downloading or decoding it again.
        base = f"{'us' if t['us'] else 'x'}-{t['region']}-{re.sub(r'[^a-z0-9]+','',t['reader'].lower())}"
        n = seen.get(base, 0); seen[base] = n + 1
        name = base if n == 0 else f"{base}{n+1}"
        dst = out / f"{name}.wav"
        if (dst.exists() and dst.stat().st_size > 10_000 and not args.force
                and dst.name in resume_index):
            manifest.append(resume_index[dst.name])
            print(f"[{i:2d}/{len(tracks)}] · {dst.name} (already staged)")
            continue

        src = cache / t["file"]
        if not src.exists():
            print(f"[{i:2d}/{len(tracks)}] downloading {t['file']} …", flush=True)
            urllib.request.urlretrieve(t["url"], src)

        pcm, sr = decode_pcm(src, 16000)
        if len(pcm) < sr * 5:
            print(f"[{i:2d}/{len(tracks)}] ✗ {t['label']}: too short after decode")
            continue
        floor = noise_floor(pcm, sr)
        body = find_body(pcm, sr, intro_guard=args.intro_guard)
        w0, w1 = pick_window(pcm, sr, body, args.seconds)

        # Cut at full source rate, then two-pass linear loudnorm (no pumping).
        cmd = ["ffmpeg", "-v", "error", "-y", "-ss", f"{w0:.3f}", "-t", f"{args.seconds:.3f}",
               "-i", str(src), "-ac", "1", "-ar", str(args.rate),
               "-af", f"loudnorm=I={args.lufs}:TP=-2.0:LRA=11:linear=true,"
                      f"afade=t=in:st=0:d=0.02,afade=t=out:st={args.seconds-0.02:.3f}:d=0.02",
               "-c:a", "pcm_s16le", str(dst)]
        r = run(cmd)
        if r.returncode != 0 or not dst.exists():
            print(f"[{i:2d}/{len(tracks)}] ✗ {t['label']}: ffmpeg failed\n{r.stderr[:300]}")
            continue

        clip_pcm, csr = decode_pcm(dst, 16000)
        q, qd = quality(clip_pcm, csr, floor)
        f0, gender = estimate_f0(dst)

        manifest.append({
            "filename": dst.name, "region": t["region"], "us": t["us"],
            "accent_label": t["label"], "reader": t["reader"],
            "gender_guess": gender, "f0_hz": f0,
            "quality_score": q, "quality": qd,
            "clip": {"start_sec": round(w0, 2), "seconds": args.seconds,
                     "body_sec": [round(body[0], 2), round(body[1], 2)],
                     "sample_rate": args.rate, "lufs": args.lufs},
            "source": {"collection": t["vol"], "item": t["item"], "file": t["file"],
                       "url": t["url"], "page": t["page"]},
            "license": LICENSE,
        })
        print(f"[{i:2d}/{len(tracks)}] ✓ {dst.name:34s} q={q:3d} "
              f"f0={f0 or '?':>5} {gender or '·'}  ({t['label']})")

    manifest.sort(key=lambda m: (-m["quality_score"], m["region"]))
    (out / "MANIFEST.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    write_sources_md(out, manifest)

    print(f"\nWrote {len(manifest)} clips + MANIFEST.json + SOURCES.md to {out}/")
    if manifest:
        print("\nListen in this order (best signal-to-noise first):")
        for m in manifest[:8]:
            print(f"   {m['quality_score']:3d}  {m['filename']:34s} {m['accent_label']}")
    print("\nNext: cull the ones you don't like, rename survivors, then\n"
          f"  python3 {Path(sys.argv[0]).name} --from-dir {out} --upload-to http://GIDEON_HOST:8101")


def write_sources_md(out: Path, manifest):
    lines = [
        "# Voice sources — LibriVox Dialect & Accent collections",
        "",
        "All clips below are derived from LibriVox recordings, which are released into",
        "the **public domain**. LibriVox's own policy: *\"LibriVox recordings are in the",
        "public domain… there is no need to credit LibriVox.\"*",
        "(<https://librivox.org/pages/public-domain/>)",
        "",
        "Safe to redistribute in an open repo or a voice marketplace. Attribution is not",
        "required — the credit lines below are courtesy, and useful for provenance.",
        "",
        "> Copyright is not consent. These readers are volunteers who published into the",
        "> public domain, which is the cleanest footing available for cloned voices — but",
        "> if any reader ever objects to a specific voice, retire it. Keep this file so",
        "> you can always answer \"where did this voice come from?\"",
        "",
        "| File | Region | Accent label (as published) | Reader | Quality | Source |",
        "|---|---|---|---|---|---|",
    ]
    for m in manifest:
        lines.append(f"| `{m['filename']}` | {m['region']} | {m['accent_label']} | "
                     f"{m['reader']} | {m['quality_score']} | [{m['source']['collection']}]"
                     f"({m['source']['url']}) |")
    lines += ["", "Generated by `scripts/stage_librivox_dialects.py`.", ""]
    (out / "SOURCES.md").write_text("\n".join(lines), encoding="utf-8")


# ── Upload ────────────────────────────────────────────────────────────────────

def split_note_name(name: str):
    """`us-midwest-dm deep slow male.wav` → (`us-midwest-dm.wav`, `deep slow male`).

    Auditioned files get a listening note appended to the filename after a space.
    The part before the first space is the MANIFEST key and becomes the (permanent,
    space-free) upload name; the rest becomes the voice's note. A name with no
    space passes through untouched.
    """
    stem, suffix = os.path.splitext(name)
    head, _, note = stem.partition(" ")
    return head + suffix, note.strip()


def do_upload(args):
    src = Path(args.from_dir)
    wavs = sorted(p for p in src.glob("*.wav"))
    if not wavs:
        sys.exit(f"No .wav files in {src}")
    base = args.upload_to.rstrip("/")

    plan = [(p, *split_note_name(p.name)) for p in wavs]
    print("⚠️  Filenames become PERMANENT once uploaded — voice_map.json files and")
    print("    AnimaForge reference them by name. Rename BEFORE this step, never after.")
    print("    Words after the first space are NOT uploaded — they become the voice's note.\n")
    for p, up_name, note in plan:
        arrow = "" if up_name == p.name else f"  →  {up_name}"
        print(f"   {p.name}{arrow}" + (f"   [note: {note}]" if note else ""))
    if input(f"\nUpload {len(wavs)} file(s) to {base}? [y/N] ").strip().lower() != "y":
        sys.exit("Aborted.")

    try:
        import requests
    except ImportError:
        sys.exit("Upload needs `requests` — run this step from the prosecast venv.")

    ok, fail, uploaded = 0, 0, []
    for p, up_name, note in plan:
        with open(p, "rb") as fh:
            r = requests.post(f"{base}/upload_predefined_voice" if args.predefined
                              else f"{base}/upload_reference",
                              files={"files": (up_name, fh, "audio/wav")}, timeout=120)
        if r.status_code < 300:
            ok += 1; uploaded.append((up_name, note)); print(f"  ✓ {up_name}")
        else:
            fail += 1; print(f"  ✗ {up_name} → HTTP {r.status_code}: {r.text[:200]}")
    print(f"\n{ok} uploaded, {fail} failed.")

    if uploaded and not args.no_meta:
        merge_voice_meta(src, uploaded, Path(args.voice_meta))
    if ok:
        print("Now hit ↻ re-check in the ProseCast header to pick up the new voices.")


def merge_voice_meta(staged_dir: Path, filenames, meta_path: Path):
    """Seed voice_meta.json from MANIFEST.json for the voices we just uploaded.

    `filenames` items are either an upload name or an `(upload name, note)` pair
    from `split_note_name`; the note lands in front of the accent label.

    Saves hand-typing the whole overlay: region, published accent label, licence
    and source URL land automatically. The gender is a PITCH GUESS — it is
    written only where the file has no entry yet, and never overwrites a label
    you set by hand. Same for notes.
    """
    mf = staged_dir / "MANIFEST.json"
    if not mf.exists():
        print(f"  (no MANIFEST.json in {staged_dir} — skipping voice_meta merge)")
        return
    try:
        by_file = {m["filename"]: m for m in json.loads(mf.read_text(encoding="utf-8"))}
    except (OSError, json.JSONDecodeError) as e:
        print(f"  (could not read MANIFEST.json: {e})")
        return

    meta = {}
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            print(f"  ⚠ {meta_path} is unreadable — not touching it.")
            return

    added = 0
    for item in filenames:
        fn, note = item if isinstance(item, tuple) else (item, "")
        m = by_file.get(fn)
        if not m:
            print(f"  (no MANIFEST entry for {fn} — no provenance seeded; add it in the Voices tab)")
            continue
        key = Path(fn).stem
        entry = dict(meta.get(key) or {})
        if not entry.get("gender"):
            entry["gender"] = m.get("gender_guess", "")
        if not entry.get("notes"):
            label = m.get("accent_label", "")
            entry["notes"] = f"{note} · {label}" if note and label else (note or label)
        entry.setdefault("region", m.get("region", ""))
        entry.setdefault("accent_label", m.get("accent_label", ""))
        entry.setdefault("license", m["license"]["spdx"])
        entry.setdefault("distributable", m["license"]["distributable"])
        entry.setdefault("source_url", m["source"]["url"])
        if key not in meta:
            added += 1
        meta[key] = entry

    meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"  → seeded {added} new entr{'y' if added == 1 else 'ies'} in {meta_path} "
          f"(gender is a pitch guess — correct it in the UI)")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(
        description="Stage Chatterbox reference clips from the LibriVox dialect collections.")
    ap.add_argument("--region", default="us",
                    help="'us' (default), 'all', or a region slug like 'texas' / 'minnesota'")
    ap.add_argument("--seconds", type=float, default=15.0,
                    help="Reference clip length. Chatterbox uses ~10-15s; longer is wasted.")
    ap.add_argument("--rate", type=int, default=44100, help="Output sample rate (source is 44.1k)")
    ap.add_argument("--lufs", type=float, default=-20.0, help="Loudness target for the bank")
    ap.add_argument("--intro-guard", type=float, default=16.0,
                    help="Seconds of spoken LibriVox boilerplate to skip at the head of every track")
    ap.add_argument("--out", default="librivox_voices")
    ap.add_argument("--cache", default=".cache/librivox")
    ap.add_argument("--force", action="store_true",
                    help="Re-cut clips that already exist (default: resume, skip them)")
    ap.add_argument("--list", action="store_true", help="List the catalogue and exit")
    ap.add_argument("--from-dir", help="Upload mode: directory of culled WAVs")
    ap.add_argument("--upload-to", help="Chatterbox server base URL, e.g. http://GIDEON_HOST:8101")
    ap.add_argument("--predefined", action="store_true",
                    help="Upload as predefined voices instead of clone references")
    ap.add_argument("--voice-meta", default="voice_meta.json",
                    help="ProseCast voice metadata overlay to seed after upload")
    ap.add_argument("--no-meta", action="store_true",
                    help="Do not touch voice_meta.json after uploading")
    args = ap.parse_args()

    if args.list:
        cache = Path(args.cache); cache.mkdir(parents=True, exist_ok=True)
        for t in fetch_catalogue(cache):
            print(f"{'US' if t['us'] else '  '}  {t['region']:18s} {t['reader']:14s} {t['label']}")
        return
    if args.from_dir:
        if not args.upload_to:
            sys.exit("--from-dir requires --upload-to")
        return do_upload(args)
    do_pull(args)


if __name__ == "__main__":
    main()
