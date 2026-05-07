from __future__ import annotations
import os
from dataclasses import dataclass, field

from .config import ProgressionConfig, MelodyConfig, MidiBuilderConfig, AudioConfig
from .chord_generator import PowerChordProgressionGenerator
from .melody_generator import MelodyGenerator
from .midi_builder import MidiBuilder
from .audio_renderer import AudioRenderer
from .scales import pitch_class_name, PITCH_CLASS_NAMES


@dataclass
class ComparisonConfig:
    root: int = 4             # E
    tempo_bpm: float = 120.0
    length_bars: int = 8
    style: str = "grunge"
    melody_config: MelodyConfig = field(default_factory=MelodyConfig)
    output_dir: str = "output/comparison"
    seed: int = 42


class ComparisonGenerator:
    """
    Runs the full pipeline twice with the same seed:
      1. Power chords (root + fifth only)
      2. Diatonic triads (same root motion, thirds added by scale membership)

    Produces side-by-side MIDI/WAV and a text summary for presentation use.
    """

    def __init__(self, config: ComparisonConfig):
        self.config = config
        os.makedirs(config.output_dir, exist_ok=True)

    def run(self, n_variations: int = 1) -> dict:
        cfg = self.config
        prog_cfg = ProgressionConfig(
            root=cfg.root,
            tempo_bpm=cfg.tempo_bpm,
            length_bars=cfg.length_bars,
            style=cfg.style,
            seed=cfg.seed,
        )

        gen = PowerChordProgressionGenerator(prog_cfg)
        power_prog = gen.generate()
        diatonic_prog = gen.generate_diatonic(power_prog, "major")

        mel_cfg = cfg.melody_config
        mel_cfg_copy = MelodyConfig(
            scale_mode=mel_cfg.scale_mode,
            temperature=mel_cfg.temperature,
            note_density=mel_cfg.note_density,
            step_weight=mel_cfg.step_weight,
            phrase_length_beats=mel_cfg.phrase_length_beats,
            octave_low=mel_cfg.octave_low,
            octave_high=mel_cfg.octave_high,
            n_variations=n_variations,
            rest_probability=mel_cfg.rest_probability,
        )

        melody_vars = MelodyGenerator(mel_cfg_copy).generate_all_variations(power_prog)
        melody = melody_vars[0]

        builder = MidiBuilder(prog_cfg, MidiBuilderConfig())
        renderer = AudioRenderer()

        power_midi = os.path.join(cfg.output_dir, "power_chords.mid")
        diatonic_midi = os.path.join(cfg.output_dir, "diatonic_chords.mid")

        builder.build(power_prog, melody, power_midi)
        builder.build_diatonic(diatonic_prog, melody, diatonic_midi)

        power_wav = renderer.render(power_midi, power_midi.replace(".mid", ".wav"))
        diatonic_wav = renderer.render(diatonic_midi, diatonic_midi.replace(".mid", ".wav"))

        summary = self._write_summary(power_prog, diatonic_prog, cfg.root)
        summary_path = os.path.join(cfg.output_dir, "comparison_summary.txt")
        with open(summary_path, "w") as f:
            f.write(summary)

        return {
            "power_chord_midi": power_midi,
            "diatonic_midi": diatonic_midi,
            "power_chord_wav": power_wav,
            "diatonic_wav": diatonic_wav,
            "summary": summary,
        }

    def _write_summary(
        self,
        power_prog: list[tuple[int, float]],
        diatonic_prog: list[tuple[int, str, float]],
        key_root: int,
    ) -> str:
        key_name = PITCH_CLASS_NAMES[key_root]

        power_str = "  ".join(f"{pitch_class_name(r)}5" for r, _ in power_prog)
        diatonic_str = "  ".join(
            f"{pitch_class_name(r)}{'m' if q=='minor' else ('°' if q=='dim' else '')}"
            for r, q, _ in diatonic_prog
        )

        # Interval analysis
        intervals = []
        for i in range(1, len(power_prog)):
            intervals.append((power_prog[i][0] - power_prog[i-1][0]) % 12)
        interval_counts = {}
        for iv in intervals:
            interval_counts[iv] = interval_counts.get(iv, 0) + 1

        # Tonality ambiguity: % of chords that don't fit C major (relative to key)
        from .scales import SCALE_INTERVALS
        major_intervals = set(SCALE_INTERVALS["major"])
        non_diatonic = sum(
            1 for r, _ in power_prog
            if (r - key_root) % 12 not in major_intervals
        )
        ambiguity_pct = 100 * non_diatonic / max(len(power_prog), 1)

        lines = [
            f"=== Comparison: {key_name} {self.config.style.title()} ({self.config.length_bars} bars) ===",
            "",
            f"Power chord progression:   {power_str}",
            f"Diatonic progression:      {diatonic_str}",
            "",
            "Interval analysis (root motion semitones):",
        ]
        interval_names = {
            0: "unison", 1: "+m2", 2: "+M2", 3: "+m3(bIII)", 4: "+M3",
            5: "+P4", 6: "+tritone", 7: "+P5", 8: "+m6", 9: "+M6(bVI)",
            10: "+m7(bVII)", 11: "-m2"
        }
        for iv, count in sorted(interval_counts.items(), key=lambda x: -x[1]):
            lines.append(f"  {interval_names.get(iv, iv):15s}  {count}x")

        lines += [
            "",
            f"Non-diatonic chords (vs {key_name} major): {non_diatonic}/{len(power_prog)} ({ambiguity_pct:.0f}%)",
            "",
            "Note: Power chords omit thirds -- no major/minor declared.",
            "The same melody plays over both progressions; the harmonic",
            "context shifts completely without changing a single melody note.",
        ]
        return "\n".join(lines)
