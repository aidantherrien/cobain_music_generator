from __future__ import annotations
import numpy as np
from dataclasses import dataclass
from typing import Literal

from .config import ProgressionConfig, MelodyConfig
from .chord_generator import PowerChordProgressionGenerator
from .melody_generator import MarkovMelodyGenerator, MelodyNote

SectionType = Literal["intro", "verse", "chorus", "bridge", "outro"]


@dataclass
class SectionConfig:
    type: SectionType
    bars: int

    velocity_scale: float = 1.0
    note_density: float = 1.0
    step_weight: float = 0.65
    rest_probability: float = 0.08
    phrase_length_beats: float = 8.0

    octave_shift: int = 0
    chord_velocity_scale: float = 1.0

    # Hook control: True = reuse the stored section hook instead of generating fresh
    use_hook: bool = True
    hook_intensity: int = 0   # 0=first occurrence, 1=second (slight vel boost)


# ── Cobain skeleton: verse heavy, chorus sparse ───────────────────────────────
#
# Cobain's verse melodies ARE the hook .
# Choruses often pull back melodically while the chords intensify -- the dynamic
# contrast comes from the arrangement (distortion, velocity), not note density.
#
# Structure: V1 -> Ch1 -> V2 -> Ch2
# Verse: dense motif-tiled hook (note_density 1.2, low rests)
# Chorus: sparse, sustained, lots of space (note_density 0.45, high rests)

DEFAULT_STRUCTURE: list[SectionConfig] = [
    SectionConfig(
        type="verse", bars=8,
        velocity_scale=0.80, note_density=1.2, step_weight=0.70,
        rest_probability=0.08, phrase_length_beats=8.0,
        chord_velocity_scale=0.80,
        use_hook=False,
    ),
    SectionConfig(
        type="chorus", bars=4,
        velocity_scale=0.85, note_density=0.45, step_weight=0.82,
        rest_probability=0.22, phrase_length_beats=8.0,
        chord_velocity_scale=1.05,
        use_hook=True, hook_intensity=0,
    ),
    SectionConfig(
        type="verse", bars=8,
        velocity_scale=0.85, note_density=1.2, step_weight=0.70,
        rest_probability=0.08, phrase_length_beats=8.0,
        chord_velocity_scale=0.85,
        use_hook=False,
    ),
    SectionConfig(
        type="chorus", bars=4,
        velocity_scale=0.90, note_density=0.45, step_weight=0.82,
        rest_probability=0.20, phrase_length_beats=8.0,
        chord_velocity_scale=1.10,
        use_hook=True, hook_intensity=1,
    ),
]


def extend_loop(chord_loop: list[tuple[int, float]], target_bars: int, beats_per_bar: int) -> list[tuple[int, float]]:
    """Repeat chord_loop until it fills target_bars, truncating the last chord if needed."""
    target_beats = target_bars * beats_per_bar
    result: list[tuple[int, float]] = []
    elapsed = 0.0
    loop_beats = sum(d for _, d in chord_loop)
    if loop_beats <= 0:
        return chord_loop

    while elapsed < target_beats:
        for root_pc, dur in chord_loop:
            remaining = target_beats - elapsed
            if remaining <= 0:
                break
            actual = min(dur, remaining)
            result.append((root_pc, actual))
            elapsed += actual
    return result


def apply_intensity(
    melody: list[MelodyNote],
    velocity_scale: float,
    octave_shift: int,
) -> list[MelodyNote]:
    """Scale velocities and optionally shift octave of a melody."""
    out = []
    for pitch, dur, vel in melody:
        if pitch == -1:
            out.append((-1, dur, 0))
        else:
            new_pitch = max(0, min(127, pitch + octave_shift * 12))
            new_vel = max(20, min(120, int(vel * velocity_scale)))
            out.append((new_pitch, dur, new_vel))
    return out


def _repeat_melody_to_fill(
    melody: list[MelodyNote],
    chord_prog: list[tuple[int, float]],
) -> list[MelodyNote]:
    """Repeat melody until its total duration matches chord_prog total beats."""
    target = sum(d for _, d in chord_prog)
    mel_dur = sum(d for _, d, _ in melody)
    if mel_dur <= 0:
        return melody
    result: list[MelodyNote] = []
    elapsed = 0.0
    while elapsed < target:
        for pitch, dur, vel in melody:
            remaining = target - elapsed
            if remaining <= 0:
                break
            actual = min(dur, remaining)
            result.append((pitch, actual, vel))
            elapsed += actual
    return result


class SongGenerator:
    """
    Generates a full song by:
      1. Creating a chord loop (repeats throughout)
      2. Generating a verse hook (stored, reused each verse)
      3. Generating a chorus hook (stored, reused each chorus -- sparse/spacious)
      4. Assembling into (SectionConfig, chord_prog, melody_notes) tuples for MidiBuilder
    """

    def __init__(
        self,
        prog_config: ProgressionConfig,
        mel_config: MelodyConfig,
        structure: list[SectionConfig] | None = None,
        song_seed: int = 42,
    ):
        self.prog_config = prog_config
        self.mel_config = mel_config
        self.structure = structure or DEFAULT_STRUCTURE
        self.song_seed = song_seed
        self._backend = MarkovMelodyGenerator()

    def _make_mel_config(self, section: SectionConfig) -> MelodyConfig:
        return MelodyConfig(
            scale_mode=self.mel_config.scale_mode,
            key_root=self.mel_config.key_root,
            modal_wander_prob=self.mel_config.modal_wander_prob,
            motif_bars=self.mel_config.motif_bars,
            temperature=self.mel_config.temperature,
            note_density=section.note_density,
            step_weight=section.step_weight,
            phrase_length_beats=section.phrase_length_beats,
            octave_low=self.mel_config.octave_low,
            octave_high=self.mel_config.octave_high,
            rest_probability=section.rest_probability,
        )

    def _gen_melody(self, chord_prog: list[tuple[int, float]], mel_cfg: MelodyConfig, seed: int) -> list[MelodyNote]:
        rng = np.random.default_rng(seed)
        return self._backend.generate_variation(chord_prog, mel_cfg, rng)

    def generate(self) -> list[tuple[SectionConfig, list[tuple[int, float]], list[MelodyNote]]]:
        """
        Returns a list of (section_config, chord_progression, melody_notes).
        chord_progression is extended to fill section.bars.
        """
        chord_loop = PowerChordProgressionGenerator(self.prog_config).generate()

        # -- Verse hook: generated once, reused across all verses (Cobain repetition)
        verse_section = next((s for s in self.structure if s.type == "verse"), None)
        if verse_section:
            verse_chord_prog = extend_loop(chord_loop, verse_section.bars, self.prog_config.beats_per_bar)
            verse_mel_cfg = self._make_mel_config(verse_section)
            base_verse = self._gen_melody(verse_chord_prog, verse_mel_cfg, self.song_seed + 1111)
        else:
            base_verse = []
            verse_chord_prog = chord_loop

        # -- Chorus hook: sparse, spacious -- generated once, reused across all choruses
        chorus_section = next((s for s in self.structure if s.type == "chorus"), None)
        if chorus_section:
            chorus_chord_prog = extend_loop(chord_loop, chorus_section.bars, self.prog_config.beats_per_bar)
            chorus_mel_cfg = self._make_mel_config(chorus_section)
            base_chorus = self._gen_melody(chorus_chord_prog, chorus_mel_cfg, self.song_seed + 9999)
        else:
            base_chorus = []
            chorus_chord_prog = chord_loop

        # -- Assemble sections
        sections = []
        verse_count = 0
        chorus_count = 0

        for i, section in enumerate(self.structure):
            chord_prog = extend_loop(chord_loop, section.bars, self.prog_config.beats_per_bar)

            if section.type == "verse":
                # Verse: reuse the stored verse hook; slight vel boost on repeat
                vel_boosts = [1.0, 1.1]
                vel_scale = section.velocity_scale * vel_boosts[min(verse_count, 1)]
                melody = apply_intensity(base_verse, vel_scale, section.octave_shift)
                # Fill if section is longer than the template verse
                if section.bars > (verse_section.bars if verse_section else section.bars):
                    melody = _repeat_melody_to_fill(melody, chord_prog)
                verse_count += 1

            elif section.type == "chorus":
                # Chorus: reuse the sparse hook with escalating intensity
                vel_boosts = [1.0, 1.15]
                vel_scale = section.velocity_scale * vel_boosts[min(chorus_count, 1)]
                melody = apply_intensity(base_chorus, vel_scale, section.octave_shift)
                if section.bars > (chorus_section.bars if chorus_section else section.bars):
                    melody = _repeat_melody_to_fill(melody, chord_prog)
                chorus_count += 1

            else:  # bridge, intro, outro (not in default skeleton, but supported)
                mel_cfg = self._make_mel_config(section)
                seed = self.song_seed + i * 77
                raw = self._gen_melody(chord_prog, mel_cfg, seed)
                melody = apply_intensity(raw, section.velocity_scale, section.octave_shift)

            sections.append((section, chord_prog, melody))

        return sections
