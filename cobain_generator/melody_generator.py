from __future__ import annotations
import numpy as np
from .config import MelodyConfig
from .scales import get_scale_pitches, get_key_blend_pitches

# MelodyNote: (midi_pitch, duration_beats, velocity)
# midi_pitch == -1 signals a rest
MelodyNote = tuple[int, float, int]


def _tile_notes(notes: list[MelodyNote], target_beats: float) -> list[MelodyNote]:
    """Repeat a melody list until its total duration reaches target_beats."""
    motif_dur = sum(d for _, d, _ in notes)
    if motif_dur <= 0:
        return notes
    result: list[MelodyNote] = []
    elapsed = 0.0
    while elapsed < target_beats - 1e-9:
        for pitch, dur, vel in notes:
            remaining = target_beats - elapsed
            if remaining <= 1e-9:
                break
            actual = min(dur, remaining)
            result.append((pitch, actual, vel))
            elapsed += actual
    return result


class MarkovMelodyGenerator:
    """
    Generates melody via a Markov chain with three constraints that produce
    Cobain-style hooks:

    1. Note repetition: self-loop weight is significant (not near-zero), so the
       melody stays on a pitch rather than hopping every beat.

    2. Contour arc: each phrase follows a parabolic rise-fall shape. The chain is
       biased toward pitches closer to a "target degree" that rises to a peak at
       the phrase midpoint and falls back to root by the end.

    3. Constrained pitch pool: primary scale + minimal borrowing (Dorian + Aeolian
       only, at low weight), keeping the pool to ~7-8 pitches rather than 11+.
    """

    MELODY_VELOCITY_BASE = 75

    def _build_transition_matrix(self, n: int, step_weight: float, temperature: float) -> np.ndarray:
        """
        n x n row-stochastic matrix.
        Self-loop gets significant weight to encourage note repetition.
        Stepwise motion preferred over leaps.
        """
        mat = np.zeros((n, n), dtype=float)
        for i in range(n):
            for j in range(n):
                dist = min(abs(i - j), n - abs(i - j))
                if dist == 0:
                    w = 0.18          # stay on same note (up from 0.01)
                elif dist == 1:
                    w = step_weight / 2.0
                elif dist == 2:
                    w = step_weight * 0.25
                else:
                    w = (1.0 - step_weight) / max(1, n - 3)
                mat[i, j] = w
            log_row = np.log(mat[i] + 1e-10)
            log_row /= max(temperature, 0.01)
            log_row -= log_row.max()
            mat[i] = np.exp(log_row)
            mat[i] /= mat[i].sum()
        return mat

    def _duration_from_density(self, density: float, rng: np.random.Generator) -> float:
        """Quarter-note base; occasionally hold (double) or use an eighth pickup."""
        base = 1.0 / max(density, 0.1)
        r = rng.random()
        if r < 0.20:    # 20% hold the note longer
            return base * 2.0
        if r < 0.25:    # 5% short pickup (reduced from 15%)
            return base * 0.5
        return base     # 75% standard quarter note

    def _generate_raw(
        self,
        total_beats: float,
        pitches: list[int],
        pitch_weights: np.ndarray,
        mat: np.ndarray,
        config: MelodyConfig,
        rng: np.random.Generator,
        start_degree: int,
        key_root: int,
    ) -> list[MelodyNote]:
        """
        Generate melody for exactly total_beats.

        Each phrase has a parabolic contour: the chain is biased toward pitches
        near a target degree that rises from root to ~65% up the scale at the
        phrase midpoint, then falls back to root.
        """
        n = len(pitches)
        notes: list[MelodyNote] = []
        phrase_beat = 0.0
        elapsed = 0.0
        current_degree = start_degree

        # Peak sits at ~65% up the scale from the starting degree
        peak_degree = min(n - 1, int(start_degree + (n - 1 - start_degree) * 0.65))

        while elapsed < total_beats - 1e-9:
            duration = self._duration_from_density(config.note_density, rng)
            duration = min(duration, total_beats - elapsed)
            if duration <= 1e-9:
                break

            # Phrase boundary: snap back to key root
            if phrase_beat >= config.phrase_length_beats:
                phrase_beat = 0.0
                target_pc = key_root % 12
                current_degree = min(range(n), key=lambda i: abs(pitches[i] % 12 - target_pc))

            if rng.random() < config.rest_probability:
                notes.append((-1, duration, 0))
            else:
                # Parabolic arc: 0->1->0 over the phrase, peak at midpoint
                t = min(phrase_beat / max(config.phrase_length_beats, 1e-9), 1.0)
                arc = 4.0 * t * (1.0 - t)
                target_deg = int(start_degree + arc * (peak_degree - start_degree))

                # Gravity pulls toward the contour target degree
                gravity = np.exp(-np.abs(np.arange(n, dtype=float) - target_deg) * 0.55)
                gravity /= gravity.sum()

                # Markov step bias (stepwise preference) × pitch pool weights
                raw_probs = mat[current_degree] * pitch_weights
                s = raw_probs.sum()
                raw_probs = raw_probs / s if s > 0 else pitch_weights.copy()

                # Blend: 60% Markov/pitch-weight, 40% contour gravity
                blended = 0.60 * raw_probs + 0.40 * gravity
                blended /= blended.sum()

                current_degree = int(rng.choice(n, p=blended))
                midi_pitch = pitches[current_degree]

                vel_noise = int(rng.integers(-8, 9))
                phrase_accent = 10 if phrase_beat < 0.05 else 0
                velocity = max(40, min(120, self.MELODY_VELOCITY_BASE + phrase_accent + vel_noise))
                notes.append((midi_pitch, duration, velocity))

            elapsed += duration
            phrase_beat += duration

        return notes

    def generate_variation(
        self,
        chord_progression: list[tuple[int, float]],
        config: MelodyConfig,
        rng: np.random.Generator,
    ) -> list[MelodyNote]:
        key_root = config.key_root if config.key_root is not None else chord_progression[0][0]

        pitches, weights = get_key_blend_pitches(
            key_root, config.scale_mode,
            config.octave_low, config.octave_high,
            config.modal_wander_prob,
        )

        if not pitches:
            pitches = get_scale_pitches(key_root, "pentatonic_minor", config.octave_low, config.octave_high)
            weights = [1.0 / len(pitches)] * len(pitches) if pitches else []

        n = len(pitches)
        if n == 0:
            return []

        pitch_weights_arr = np.array(weights, dtype=float)
        mat = self._build_transition_matrix(n, config.step_weight, config.temperature)

        # Start on the pitch closest to the key root
        target_pc = key_root % 12
        start_degree = min(range(n), key=lambda i: abs(pitches[i] % 12 - target_pc))

        total_beats = sum(d for _, d in chord_progression)

        # Motif tiling: generate a short phrase, tile it across the section
        if config.motif_bars > 0:
            motif_beats = min(config.motif_bars * 4, total_beats)
            motif = self._generate_raw(
                motif_beats, pitches, pitch_weights_arr, mat, config, rng, start_degree, key_root
            )
            return _tile_notes(motif, total_beats)

        return self._generate_raw(
            total_beats, pitches, pitch_weights_arr, mat, config, rng, start_degree, key_root
        )


class MelodyGenerator:
    """Top-level facade -- generates n_variations independent melodies."""

    def __init__(self, config: MelodyConfig):
        self.config = config
        self.backend = MarkovMelodyGenerator()

    def generate_all_variations(
        self,
        chord_progression: list[tuple[int, float]],
    ) -> list[list[MelodyNote]]:
        seed = getattr(self.config, 'seed', 42) or 42
        variations = []
        for i in range(self.config.n_variations):
            rng = np.random.default_rng(seed + i * 1000)
            variation = self.backend.generate_variation(chord_progression, self.config, rng)
            variations.append(variation)
        return variations
