#!/usr/bin/env bash
# Synthesize all default BGM + SFX via ffmpeg.
# Re-run any time to regenerate. Output goes to ./bgm/ and ./sfx/.
#
# Audio design:
#   BGM are 30-second seamless loops, ~-25 dB, designed to fade into the
#   background under narrative reading. Each style picks chord/timbre:
#     dark      — sub-drone + distant high bell (sparse)
#     horror    — minor-second clash with slow tremolo
#     healing   — sus2 chord pad with gentle vibrato
#     realistic — neutral perfect-fifth drone
#     comedy    — bright two-note ostinato in major
#
#   SFX are < 0.5s, peaking ~-12 dB:
#     dice      — falling chirp ("thud")
#     state_up  — two-note ascending chime (C5 → E5)
#     state_down — two-note descending dud (G4 → Eb4)

set -e
cd "$(dirname "$0")"
mkdir -p bgm sfx

ENC="-codec:a libmp3lame -q:a 4"

echo "== BGM ==" >&2

# dark: 55Hz sub + 110Hz octave + sparse 880Hz bell on every 5s
ffmpeg -y -hide_banner -loglevel error \
  -f lavfi -i "sine=frequency=55:duration=30" \
  -f lavfi -i "sine=frequency=110:duration=30" \
  -f lavfi -i "aevalsrc=0.5*sin(2*PI*880*t)*exp(-2.5*mod(t\,5)):d=30" \
  -filter_complex "[0:a][1:a]amix=inputs=2:weights='1 0.4'[drone];[2:a]volume=0.18[bell];[drone][bell]amix=inputs=2:weights='1 1'[mix];[mix]volume=0.35,afade=t=in:st=0:d=2,afade=t=out:st=28:d=2" \
  -t 30 $ENC bgm/dark.mp3

# horror: minor-second 110Hz + 117Hz with slow tremolo
ffmpeg -y -hide_banner -loglevel error \
  -f lavfi -i "sine=frequency=110:duration=30" \
  -f lavfi -i "sine=frequency=117:duration=30" \
  -f lavfi -i "sine=frequency=233:duration=30" \
  -filter_complex "[0:a][1:a][2:a]amix=inputs=3:weights='1 0.7 0.3'[mix];[mix]tremolo=f=1.5:d=0.6,volume=0.3,afade=t=in:st=0:d=2,afade=t=out:st=28:d=2" \
  -t 30 $ENC bgm/horror.mp3

# healing: C-E-G major chord (C4 + E4 + G4) with vibrato
ffmpeg -y -hide_banner -loglevel error \
  -f lavfi -i "sine=frequency=261.63:duration=30" \
  -f lavfi -i "sine=frequency=329.63:duration=30" \
  -f lavfi -i "sine=frequency=392.00:duration=30" \
  -filter_complex "[0:a][1:a][2:a]amix=inputs=3:weights='1 0.7 0.7'[mix];[mix]vibrato=f=0.4:d=0.05,volume=0.22,afade=t=in:st=0:d=2,afade=t=out:st=28:d=2" \
  -t 30 $ENC bgm/healing.mp3

# realistic: C3 + G3 perfect fifth, no flair
ffmpeg -y -hide_banner -loglevel error \
  -f lavfi -i "sine=frequency=130.81:duration=30" \
  -f lavfi -i "sine=frequency=196.00:duration=30" \
  -filter_complex "[0:a][1:a]amix=inputs=2:weights='1 0.6'[mix];[mix]volume=0.20,afade=t=in:st=0:d=2,afade=t=out:st=28:d=2" \
  -t 30 $ENC bgm/realistic.mp3

# comedy: bouncing 0.25s C5 → E5 ostinato
ffmpeg -y -hide_banner -loglevel error \
  -f lavfi -i "aevalsrc=0.5*sin(2*PI*(523+131*floor(mod(2*t\,2)))*t):d=30" \
  -af "afade=t=in:st=0:d=2,afade=t=out:st=28:d=2,volume=0.20" \
  -t 30 $ENC bgm/comedy.mp3

echo "== SFX ==" >&2

# dice: short falling chirp
ffmpeg -y -hide_banner -loglevel error \
  -f lavfi -i "aevalsrc=sin(2*PI*(220-1800*t)*t):d=0.08" \
  -af "afade=t=out:st=0:d=0.08,volume=0.6" \
  $ENC sfx/dice.mp3

# state_up: C5 → E5 ascending chime
ffmpeg -y -hide_banner -loglevel error \
  -f lavfi -i "sine=frequency=523.25:duration=0.12" \
  -f lavfi -i "sine=frequency=659.26:duration=0.18" \
  -filter_complex "[0:a]afade=t=out:st=0.04:d=0.08[a];[1:a]adelay=110|110,afade=t=out:st=0.06:d=0.13[b];[a][b]amix=inputs=2:weights='1 1',volume=0.5" \
  $ENC sfx/state_up.mp3

# state_down: G4 → Eb4 descending dud
ffmpeg -y -hide_banner -loglevel error \
  -f lavfi -i "sine=frequency=392.00:duration=0.12" \
  -f lavfi -i "sine=frequency=311.13:duration=0.20" \
  -filter_complex "[0:a]afade=t=out:st=0.04:d=0.08[a];[1:a]adelay=110|110,afade=t=out:st=0.06:d=0.15[b];[a][b]amix=inputs=2:weights='1 1',volume=0.5" \
  $ENC sfx/state_down.mp3

# legacy: keep silence.mp3 around as a no-op fallback
ffmpeg -y -hide_banner -loglevel error \
  -f lavfi -i "anullsrc=r=44100:cl=mono" -t 1 $ENC bgm/silence.mp3
cp bgm/silence.mp3 sfx/silence.mp3

echo "" >&2
echo "Generated:" >&2
ls -lh bgm/*.mp3 sfx/*.mp3 | awk '{printf "  %-40s %s\n", $9, $5}' >&2
