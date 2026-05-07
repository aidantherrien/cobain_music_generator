from __future__ import annotations
import numpy as np
from .config import ProgressionConfig
from .scales import pitch_class_name

# Markov interval weight vector indexed 0..11 (semitones mod 12 from current root).
# Calibrated against Cobain catalog: In Bloom, SLTS, Come As You Are, Heart-Shaped Box,
# Lithium, About a Girl, Polly, Frances Farmer, Rape Me, Pennyroyal Tea.
BASE_INTERVAL_WEIGHTS = np.array([
    0.05,  # 0  - unison (pedal / repeat — Heart-Shaped Box verse)
    0.04,  # 1  - +m2 (chromatic neighbor)
    0.08,  # 2  - +M2 (whole step up)
    0.12,  # 3  - +m3 = bIII (About a Girl: E→G, Come As You Are: A→C)
    0.04,  # 4  - +M3 (rare; Polly-style)
    0.14,  # 5  - +P4 = IV (standard rock motion)
    0.03,  # 6  - +tritone (chromatic saturation, In Bloom mode)
    0.10,  # 7  - +P5
    0.04,  # 8  - +m6
    0.16,  # 9  - +M6 = bVI down (Heart-Shaped Box: A→F, In Bloom — STRONGEST fingerprint)
    0.09,  # 10 - +m7 = bVII (Smells Like Teen Spirit: A→G riff)
    0.11,  # 11 - -m2 (chromatic half-step down)
], dtype=float)

# Per-style multipliers applied to BASE_INTERVAL_WEIGHTS before normalizing
STYLE_BIAS: dict[str, dict[int, float]] = {
    "grunge": {3: 1.5, 9: 1.8, 10: 1.6, 5: 1.2, 7: 0.5, 0: 0.5},
    "verse":  {0: 2.0, 5: 1.3, 3: 1.1, 7: 0.7, 9: 1.2},
    "chorus": {5: 1.5, 10: 1.5, 3: 1.2, 7: 1.0, 6: 1.3, 9: 1.2},
    "chromatic": {i: 1.0 for i in range(12)},  # flatten — In Bloom mode
    "ballad": {0: 1.5, 5: 1.5, 7: 1.2, 9: 1.0, 2: 1.2, 3: 0.8},
}

# Duration options in beats, with weights per style
DURATION_OPTIONS = {
    "grunge":    [(2.0, 0.2), (4.0, 0.6), (8.0, 0.2)],
    "verse":     [(4.0, 0.5), (8.0, 0.3), (2.0, 0.2)],
    "chorus":    [(2.0, 0.4), (4.0, 0.5), (1.0, 0.1)],
    "chromatic": [(2.0, 0.3), (4.0, 0.5), (1.0, 0.2)],
    "ballad":    [(4.0, 0.4), (8.0, 0.4), (2.0, 0.2)],
}


class PowerChordProgressionGenerator:
    def __init__(self, config: ProgressionConfig):
        self.config = config
        self.rng = np.random.default_rng(config.seed)

    def _build_transition_probs(self, style: str) -> np.ndarray:
        weights = BASE_INTERVAL_WEIGHTS.copy()
        bias = STYLE_BIAS.get(style, {})
        for interval, multiplier in bias.items():
            weights[interval] *= multiplier
        if style == "chromatic":
            weights = np.ones(12)
        weights /= weights.sum()

        # Blend toward flat distribution for unconventional harmonic motion.
        # unconventional=0 -> pure style, unconventional=1 -> all 12 intervals equal.
        u = getattr(self.config, "unconventional", 0.0)
        if u > 0:
            flat = np.ones(12, dtype=float) / 12.0
            weights = (1.0 - u) * weights + u * flat

        return weights

    def _sample_next_root(self, current: int, probs: np.ndarray) -> int:
        interval = self.rng.choice(12, p=probs)
        return (current + interval) % 12

    def _sample_duration(self, style: str) -> float:
        if not self.config.allow_duration_variation:
            return self.config.chord_duration_beats
        opts = DURATION_OPTIONS.get(style, DURATION_OPTIONS["grunge"])
        durations, weights = zip(*opts)
        weights = np.array(weights, dtype=float)
        weights /= weights.sum()
        return float(self.rng.choice(durations, p=weights))

    def _generate_fixed_count(self, n_chords: int) -> list[tuple[int, float]]:
        """Generate exactly n_chords chords with equal duration — the Cobain loop approach."""
        total_beats = self.config.length_bars * self.config.beats_per_bar
        beat_per_chord = total_beats / n_chords
        probs = self._build_transition_probs(self.config.style)
        progression: list[tuple[int, float]] = []
        current = self.config.root
        for _ in range(n_chords):
            progression.append((current, beat_per_chord))
            current = self._sample_next_root(current, probs)
        return progression

    def generate(self) -> list[tuple[int, float]]:
        n_chords = getattr(self.config, "n_chords", None)
        if n_chords is not None and n_chords > 0:
            return self._generate_fixed_count(n_chords)

        probs = self._build_transition_probs(self.config.style)
        total_beats = self.config.length_bars * self.config.beats_per_bar
        progression: list[tuple[int, float]] = []
        current_root = self.config.root
        elapsed = 0.0

        while elapsed < total_beats:
            duration = self._sample_duration(self.config.style)
            duration = min(duration, total_beats - elapsed)
            if duration <= 0:
                break
            progression.append((current_root, duration))
            elapsed += duration
            current_root = self._sample_next_root(current_root, probs)

        return progression

    def generate_diatonic(
        self,
        power_prog: list[tuple[int, float]],
        scale: str = "major",
    ) -> list[tuple[int, str, float]]:
        """Assign chord quality to an existing progression by diatonic scale membership."""
        from .scales import SCALE_INTERVALS, MAJOR_SCALE_QUALITIES, MINOR_SCALE_QUALITIES
        key_root = self.config.root
        scale_intervals = SCALE_INTERVALS.get(scale, SCALE_INTERVALS["major"])
        qualities = MAJOR_SCALE_QUALITIES if scale == "major" else MINOR_SCALE_QUALITIES

        diatonic = []
        for root_pc, duration in power_prog:
            interval = (root_pc - key_root) % 12
            if interval in scale_intervals:
                degree_idx = scale_intervals.index(interval)
                quality = qualities[degree_idx % len(qualities)]
            else:
                # Non-diatonic: pick closest diatonic or label as borrowed
                quality = "major"
            diatonic.append((root_pc, quality, duration))
        return diatonic

    def describe(self, progression: list[tuple[int, float]]) -> str:
        return "  ".join(f"{pitch_class_name(r)}5({d:.1f}b)" for r, d in progression)
