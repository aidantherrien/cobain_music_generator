from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class ProgressionConfig:
    root: int = 4
    # Pitch class of starting root: C=0, C#=1, D=2, Eb=3, E=4, F=5, F#=6, G=7, Ab=8, A=9, Bb=10, B=11
    tempo_bpm: float = 120.0
    length_bars: int = 8
    beats_per_bar: int = 4
    style: str = "verse"
    # "grunge" | "verse" | "chorus" | "chromatic" | "ballad"
    chord_duration_beats: float = 4.0
    allow_duration_variation: bool = True
    seed: int | None = 42
    unconventional: float = 0.05
    # 0.0 = pure Cobain style weights, 1.0 = flat chromatic (all intervals equally likely).
    # 0.2 is a mild push toward stranger root motions (tritone, m2, m6 get more weight).

    n_chords: int | None = None
    # Exact number of chords in the loop (all equal duration).
    # None = fill length_bars with variable-duration chords (wandering Markov walk).
    # Set to 4 for a 4-chord loop like Teen Spirit, 6-8 for Lithium-style patterns.
    # When set, chord_duration = (length_bars * beats_per_bar) / n_chords.


@dataclass
class MelodyConfig:
    scale_mode: str = "aeolian"
    # Primary scale, anchored to key_root (not the current chord).
    # "pentatonic_minor" | "pentatonic_major" | "dorian" | "mixolydian" |
    # "phrygian" | "aeolian" | "chromatic" | "blues" | "lydian" | "locrian"

    key_root: int | None = None
    # Global tonic for the song (0=C, 4=E, 9=A, etc.).
    # None = use the progression's root. When set, melody stays anchored here
    # regardless of which chord is playing underneath â€” Cobain style.

    modal_wander_prob: float = 0.07
    # Probability weight given to notes borrowed from parallel modes (b3, b6, b7 etc.)
    # relative to primary-scale notes (weight 1.0). 0=strict key, 0.4=frequent wandering.
    # Cobain sweet spot: ~0.15-0.25 â€” mostly in key, occasional modal colour.

    motif_bars: int = 4
    # Generate a melodic motif this many bars long, then tile it across the section.
    # Creates the repetitive hook quality of Cobain verse/chorus melodies.

    temperature: float = 0.5
    # Randomness of note selection within the weighted pitch pool (0.1=predictable).

    note_density: float = 1.0
    # Approximate notes per beat. 0.5=half notes, 2.0=eighth notes.

    step_weight: float = 0.65
    # Probability of stepwise motion vs leaps (0=all leaps, 1=all steps).

    phrase_length_beats: float = 8.0
    # Beats before melodic phrase resets to an anchor tone.

    octave_low: int = 4
    octave_high: int = 5
    # MIDI octave range (Cobain vocal range ~octave 3-5, middle C = octave 4).

    n_variations: int = 5
    rest_probability: float = 0.08

    backend: str = "markov"


@dataclass
class MidiBuilderConfig:
    chord_program: int = 4     # GM: Electric Piano 1 (Tine EP / suitcase-style)
    melody_program: int = 4    # GM: Electric Piano 1 (Tine EP / suitcase-style)
    bass_program: int = 33     # GM: Acoustic Bass
    chord_velocity: int = 90
    melody_velocity_base: int = 75
    bass_velocity: int = 70
    chord_channel: int = 0
    melody_channel: int = 1
    bass_channel: int = 2
    drum_channel: int = 9
    include_bass: bool = True
    include_drums: bool = False
    ticks_per_beat: int = 480


@dataclass
class AudioConfig:
    soundfont_path: str | None = None
    sample_rate: int = 44100
    gain: float = 0.8
    reverb: bool = True

