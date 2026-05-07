from __future__ import annotations
import os
import shutil
import subprocess
import mido
from mido import MidiFile, MidiTrack, Message, MetaMessage

PITCH_NAMES = ['C', 'C#', 'D', 'Eb', 'E', 'F', 'F#', 'G', 'Ab', 'A', 'Bb', 'B']

# Curated Kurt Cobain 4-chord power-chord templates.
# offsets: semitones above the tonic (I = 0).
TEMPLATES: dict[str, dict] = {
    "slts": {
        "name": "Smells Like Teen Spirit",
        "offsets": [0, 5, 3, 8],    # I  IV  bIII  bVI
        "contour": "rises to IV, drops to bIII, falls further to bVI",
        "notes": "Classic Cobain axis between IV, bIII, and bVI",
    },

    "rape_me": {
        "name": "Rape Me",
        "offsets": [0, 3, 7, 10],   # I  bIII  V  bVII
        "contour": "minor-third rise, jumps to V, resolves upward to bVII",
        "notes": "A5 -> C5 -> E5 -> G5 outlines stacked minor-third motion",
    },

    "polly": {
        "name": "Polly",
        "offsets": [0, 3, 10, 8],   # I  bIII  bVII  bVI
        "contour": "minor-third rise followed by descending whole-step motion",
        "notes": "E5 -> G5 -> D5 -> C5 drifts downward through modal degrees",
    },

    "heart_shaped": {
        "name": "Heart-Shaped Box",
        "offsets": [0, 8, 5, 5],       # I  bVI  IV
        "contour": "falls to bVI, then rises slightly to IV",
        "notes": "The bVI is the emotional center; the return to IV never fully resolves",
    },

    # Honestly difficult to reduce cleanly to one reusable Cobain template.
    # The riff is more chromatic/voice-led than archetypal.
    "in_bloom": {
        "name": "In Bloom",
        "offsets": [0, 10, 1, 5],   # I  bVII  bII  IV
        "contour": "drops to bVII, chromatically shifts upward, then lands on IV",
        "notes": "More chromatic and riff-driven than modal; not a clean archetype",
    },

    "andalusian": {
        "name": "Andalusian Descent",
        "offsets": [0, 10, 8, 7],   # I  bVII  bVI  V
        "contour": "stepwise descent through modal degrees toward V",
        "notes": "Classic Andalusian cadence used constantly in rock and grunge",
    },

    "drain_you": {
        "name": "Drain You",
        "offsets": [0, 4, 9, 2],    # I  III  VI  II
        "contour": "cyclical upward motion by fourth/fifth relationships",
        "notes": "A5 -> C#5 -> F#5 -> B5 forms a chain of dominant-style root motion",
    },

}

_SOUNDFONT = r"C:\Users\aidan\VSCode Projects\MUSC448C Final Project\assets\soundfonts\GeneralUser_GS_v1.471.sf2"
_FLUIDSYNTH_CANDIDATES = [
    r"C:\fluidsynth\fluidsynth-v2.5.4-win10-x64-cpp11\bin\fluidsynth.exe",
    r"C:\Program Files\FluidSynth\bin\fluidsynth.exe",
    r"C:\fluidsynth\bin\fluidsynth.exe",
]


def _fluidsynth_exe() -> str | None:
    if found := shutil.which("fluidsynth"):
        return found
    for p in _FLUIDSYNTH_CANDIDATES:
        if os.path.exists(p):
            return p
    return None


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def build_progression(
    tonic: int,
    template: str,
    beats_per_chord: float = 4.0,
    n_loops: int = 2,
) -> list[tuple[int, float]]:
    """Return (pitch_class, duration_beats) pairs for one or more loops."""
    offsets = TEMPLATES[template]["offsets"]
    loop = [((tonic + o) % 12, beats_per_chord) for o in offsets]
    return loop * n_loops


def label(tonic: int, template: str) -> str:
    """Human-readable chord names, e.g. 'E5  →  A5  →  G5  →  C5'."""
    offsets = TEMPLATES[template]["offsets"]
    roots = [PITCH_NAMES[(tonic + o) % 12] for o in offsets]
    return "  ->  ".join(f"{r}5" for r in roots)


def to_midi(
    progression: list[tuple[int, float]],
    output_path: str,
    tempo_bpm: float = 120.0,
    program: int = 4,       # GM 4 = Electric Piano 1 (tine EP)
    velocity: int = 82,
    ticks_per_beat: int = 480,
) -> str:
    """Write a MIDI file containing only power chords (root + fifth + octave)."""
    tempo_us = int(60_000_000 / tempo_bpm)
    mid = MidiFile(ticks_per_beat=ticks_per_beat)

    # Track 0: tempo / time signature
    meta = MidiTrack()
    meta.append(MetaMessage("set_tempo", tempo=tempo_us, time=0))
    meta.append(MetaMessage(
        "time_signature", numerator=4, denominator=4,
        clocks_per_click=24, notated_32nd_notes_per_beat=8, time=0,
    ))
    meta.append(MetaMessage("end_of_track", time=0))
    mid.tracks.append(meta)

    # Track 1: chords
    chords = MidiTrack()
    chords.append(Message("program_change", channel=0, program=program, time=0))

    abs_tick = 0
    last_tick = 0

    for root_pc, dur_beats in progression:
        dur_ticks  = int(round(dur_beats * ticks_per_beat))
        gate_ticks = int(round(dur_ticks * 0.88))  # slight gap between chords

        root_midi  = root_pc + 48   # C3 = 48
        fifth_midi = root_midi + 7
        oct_midi   = root_midi + 12

        # Note-on (delta from last event)
        chords.append(Message("note_on",  channel=0, note=root_midi,  velocity=velocity,     time=abs_tick - last_tick))
        chords.append(Message("note_on",  channel=0, note=fifth_midi, velocity=velocity - 5, time=0))
        chords.append(Message("note_on",  channel=0, note=oct_midi,   velocity=velocity - 8, time=0))
        last_tick = abs_tick

        # Note-off (delta from the note_on batch above)
        chords.append(Message("note_off", channel=0, note=root_midi,  velocity=0, time=gate_ticks))
        chords.append(Message("note_off", channel=0, note=fifth_midi, velocity=0, time=0))
        chords.append(Message("note_off", channel=0, note=oct_midi,   velocity=0, time=0))
        last_tick = abs_tick + gate_ticks

        abs_tick += dur_ticks

    chords.append(MetaMessage("end_of_track", time=0))
    mid.tracks.append(chords)

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    mid.save(output_path)
    return output_path


def to_midi_with_melody(
    progression: list[tuple[int, float]],
    melody: list[tuple[int, float, int]],
    output_path: str,
    tempo_bpm: float = 120.0,
    chord_program: int = 4,     # GM 4 = Electric Piano 1
    melody_program: int = 4,
    chord_velocity: int = 72,
    ticks_per_beat: int = 480,
) -> str:
    """Write a two-track MIDI: power chords on ch 0, single-note melody on ch 1."""
    tempo_us = int(60_000_000 / tempo_bpm)
    mid = MidiFile(ticks_per_beat=ticks_per_beat)

    # Track 0: meta
    meta = MidiTrack()
    meta.append(MetaMessage("set_tempo", tempo=tempo_us, time=0))
    meta.append(MetaMessage(
        "time_signature", numerator=4, denominator=4,
        clocks_per_click=24, notated_32nd_notes_per_beat=8, time=0,
    ))
    meta.append(MetaMessage("end_of_track", time=0))
    mid.tracks.append(meta)

    # Track 1: chords (same logic as to_midi)
    chords = MidiTrack()
    chords.append(Message("program_change", channel=0, program=chord_program, time=0))
    abs_tick = 0
    last_tick = 0
    for root_pc, dur_beats in progression:
        dur_ticks  = int(round(dur_beats * ticks_per_beat))
        gate_ticks = int(round(dur_ticks * 0.88))
        root_midi  = root_pc + 48
        fifth_midi = root_midi + 7
        oct_midi   = root_midi + 12
        chords.append(Message("note_on",  channel=0, note=root_midi,  velocity=chord_velocity,     time=abs_tick - last_tick))
        chords.append(Message("note_on",  channel=0, note=fifth_midi, velocity=chord_velocity - 5, time=0))
        chords.append(Message("note_on",  channel=0, note=oct_midi,   velocity=chord_velocity - 8, time=0))
        last_tick = abs_tick
        chords.append(Message("note_off", channel=0, note=root_midi,  velocity=0, time=gate_ticks))
        chords.append(Message("note_off", channel=0, note=fifth_midi, velocity=0, time=0))
        chords.append(Message("note_off", channel=0, note=oct_midi,   velocity=0, time=0))
        last_tick = abs_tick + gate_ticks
        abs_tick += dur_ticks
    chords.append(MetaMessage("end_of_track", time=0))
    mid.tracks.append(chords)

    # Track 2: melody — single notes, channel 1
    mel_track = MidiTrack()
    mel_track.append(Message("program_change", channel=1, program=melody_program, time=0))
    abs_tick = 0
    last_tick = 0
    for pitch, dur_beats, vel in melody:
        dur_ticks = int(round(dur_beats * ticks_per_beat))
        if pitch == -1:             # rest: advance time, no events
            abs_tick += dur_ticks
            continue
        gate_ticks = int(round(dur_ticks * 0.92))
        mel_track.append(Message("note_on",  channel=1, note=pitch, velocity=vel, time=abs_tick - last_tick))
        last_tick = abs_tick
        mel_track.append(Message("note_off", channel=1, note=pitch, velocity=0, time=gate_ticks))
        last_tick = abs_tick + gate_ticks
        abs_tick += dur_ticks
    mel_track.append(MetaMessage("end_of_track", time=0))
    mid.tracks.append(mel_track)

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    mid.save(output_path)
    return output_path


def to_wav(midi_path: str, wav_path: str, gain: float = 0.8) -> str | None:
    """Render MIDI to WAV via FluidSynth. Returns wav_path or None if unavailable."""
    fs = _fluidsynth_exe()
    if fs is None:
        print("[progressions] FluidSynth not found — MIDI saved, WAV skipped.")
        return None
    if not os.path.exists(_SOUNDFONT):
        print(f"[progressions] Soundfont not found at {_SOUNDFONT} — WAV skipped.")
        return None

    cmd = [
        fs, "-ni",
        "-F", wav_path,
        "-r", "44100",
        "-g", str(gain),
        "--reverb", "yes",
        _SOUNDFONT, midi_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"[progressions] FluidSynth error:\n{result.stderr}")
        return None
    return wav_path


def render(
    tonic: int,
    template: str,
    output_dir: str = "output/progressions",
    tempo_bpm: float = 120.0,
    beats_per_chord: float = 4.0,
    n_loops: int = 2,
) -> tuple[str, str | None]:
    """
    Build progression → write MIDI → render WAV.
    Returns (midi_path, wav_path).  wav_path is None if FluidSynth is unavailable.
    """
    tonic_name = PITCH_NAMES[tonic % 12]
    stem      = f"{tonic_name}_{template}"
    midi_path = os.path.join(output_dir, f"{stem}.mid")
    wav_path  = os.path.join(output_dir, f"{stem}.wav")
    os.makedirs(output_dir, exist_ok=True)

    prog = build_progression(tonic, template, beats_per_chord, n_loops)
    to_midi(prog, midi_path, tempo_bpm=tempo_bpm)
    wav = to_wav(midi_path, wav_path)

    tmpl = TEMPLATES[template]
    print(f"\n[{tmpl['name']}]")
    print(f"  chords  : {label(tonic, template)}")
    print(f"  contour : {tmpl['contour']}")
    print(f"  midi    : {midi_path}")
    if wav:
        print(f"  wav     : {wav}")

    return midi_path, wav


# ---------------------------------------------------------------------------
# Quick demo when run directly
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Render all eight templates in E (pitch class 4)
    for t in TEMPLATES:
        render(tonic=4, template=t)
