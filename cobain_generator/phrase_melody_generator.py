from __future__ import annotations
import math
import numpy as np
from .scales import get_scale_pitches

# Rhythm templates per phrase type — all sum to 4.0 beats.
# Scaled proportionally when phrase_length_beats != 4.0.
RHYTHM_TEMPLATES: dict[str, list[list[float]]] = {
    "question": [
        [0.5, 0.5, 1.0, 2.0],           # pickup + climb + hold
        [1.0, 1.0, 2.0],                 # steady 3-note ascent
        [0.5, 0.5, 0.5, 0.5, 2.0],      # eighth-note run to held note
        [0.75, 0.25, 1.5, 1.5],          # dotted-eighth anticipation
        [0.5, 0.5, 0.5, 0.5, 0.5, 1.5], # quick run + delayed resolve
        [1.0, 0.5, 0.5, 1.0, 1.0],      # step + double-time + step
        [0.5, 1.0, 0.5, 2.0],           # offbeat entry + climb
    ],
    "answer": [
        [2.0, 1.0, 1.0],                 # hold at top + step down
        [1.0, 0.5, 0.5, 2.0],           # descend then resolve
        [2.0, 0.5, 0.5, 1.0],           # held top + quick steps
        [1.5, 0.5, 1.0, 1.0],           # syncopated start
        [0.5, 0.5, 1.0, 1.0, 1.0],      # quick entry + even descent
        [3.0, 1.0],                       # long tension + final drop
        [1.0, 1.0, 0.5, 0.5, 1.0],      # mid-phrase syncopation
    ],
    "pedal": [
        [1.0, 1.0, 1.0, 1.0],           # four quarters
        [2.0, 2.0],                       # two halves
        [1.0, 1.0, 2.0],                 # two quarters + half
        [0.5, 0.5, 0.5, 0.5, 1.0, 1.0], # eighth run + settle
        [0.5, 1.5, 0.5, 1.5],            # syncopated pairs
        [0.75, 0.25, 0.75, 0.25, 2.0],  # gallop + hold
        [1.0, 0.5, 0.5, 1.0, 1.0],      # 3+2 feel
        [0.5, 0.5, 1.0, 0.5, 0.5, 1.0], # eighth + quarter ostinato
    ],
}


def _clamp(val: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, val))


def _scale_rhythm(template: list[float], phrase_beats: float) -> list[float]:
    factor = phrase_beats / 4.0
    return [d * factor for d in template]


def _build_phrase_sequence(
    phrase_type: str,
    n_phrases: int,
    rng: np.random.Generator,
) -> list[str]:
    if phrase_type != "auto":
        return [phrase_type] * n_phrases

    seq = []
    for i in range(n_phrases):
        base = "question" if i % 2 == 0 else "answer"
        if i % 2 == 1 and rng.random() < 0.25:
            seq.append("pedal")
        else:
            seq.append(base)
    return seq


def _stepwise_path(
    pitches: list[int],
    start_idx: int,
    end_idx: int,
    n_steps: int,
) -> list[int]:
    """
    Deterministic plan: n_steps scale-degree indices moving from start_idx to
    end_idx in equal-ish increments.  Randomness is applied separately via
    _temperature_pick so the two concerns stay cleanly separated.
    """
    if n_steps <= 0:
        return []
    if n_steps == 1:
        return [end_idx]

    n = len(pitches)
    path = []
    cur = start_idx

    for step in range(n_steps):
        path.append(cur)
        remaining_steps = n_steps - step - 1
        if remaining_steps == 0:
            break

        remaining_dist = end_idx - cur
        if remaining_dist == 0:
            cur = end_idx
            continue

        direction = 1 if remaining_dist > 0 else -1
        move = math.ceil(abs(remaining_dist) / remaining_steps) * direction
        cur = _clamp(cur + move, 0, n - 1)

    while len(path) < n_steps:
        path.append(end_idx)

    return path


def _temperature_pick(
    target_idx: int,
    n: int,
    temperature: float,
    rng: np.random.Generator,
) -> int:
    """
    Sample a scale-degree index near target_idx using a softmax distribution
    over linear distance.  Temperature controls how peaked the distribution is:
      0.0  → always returns target_idx exactly (deterministic)
      0.5  → usually neighbours, occasional wider jumps
      1.0  → significant spread across the scale
      1.5  → nearly uniform — any scale degree is fair game
    This is what makes the Temperature slider audible.
    """
    if temperature <= 0.0 or n <= 1:
        return target_idx
    logits = -np.abs(np.arange(n, dtype=float) - target_idx)
    logits /= max(float(temperature), 0.05)
    logits -= logits.max()
    weights = np.exp(logits)
    weights /= weights.sum()
    return int(rng.choice(n, p=weights))


def _apply_syncopation(
    notes: list[tuple[int, float, int]],
    syncopation: float,
    rng: np.random.Generator,
) -> list[tuple[int, float, int]]:
    """
    Anticipation syncopation: a note arrives 0.25 beats early by borrowing
    time from the note before it.  The anticipated note gets a small velocity
    bump (off-beat accent), matching the feel of Cobain's pushed vocal lines.
    Only applied to consecutive real notes where the donor has >= 0.5 beats.
    Skips the note after each edit to prevent cascading anticipations.
    """
    if syncopation <= 0 or len(notes) < 2:
        return notes

    result = list(notes)
    i = 0
    while i < len(result) - 1:
        pitch, dur, vel = result[i]
        n_pitch, n_dur, n_vel = result[i + 1]
        if (pitch != -1 and n_pitch != -1
                and dur >= 0.5
                and n_dur >= 0.25
                and rng.random() < syncopation * 0.4):
            result[i]     = (pitch,   dur  - 0.25, vel)
            result[i + 1] = (n_pitch, n_dur + 0.25, min(120, n_vel + 6))
            i += 2  # skip the just-shifted note so we don't cascade
        else:
            i += 1
    return result


def _trim_to_beats(
    notes: list[tuple[int, float, int]],
    target_beats: float,
) -> list[tuple[int, float, int]]:
    out = []
    elapsed = 0.0
    for pitch, dur, vel in notes:
        if elapsed >= target_beats:
            break
        dur = min(dur, target_beats - elapsed)
        out.append((pitch, dur, vel))
        elapsed += dur
    return out


def _tile_notes(
    motif: list[tuple[int, float, int]],
    target_beats: float,
) -> list[tuple[int, float, int]]:
    if not motif:
        return []
    motif_len = sum(d for _, d, _ in motif)
    if motif_len <= 0:
        return []
    out: list[tuple[int, float, int]] = []
    elapsed = 0.0
    while elapsed < target_beats:
        for pitch, dur, vel in motif:
            remaining = target_beats - elapsed
            if remaining <= 0:
                break
            actual = min(dur, remaining)
            out.append((pitch, actual, vel))
            elapsed += actual
    return out


def _resolve_apex_idx(
    pitches: list[int],
    config,
    key_root: int,
    octave_low: int,
    root_idx: int,
) -> int:
    """
    Find the apex (tension/goal) scale-degree index.
    Uses config.apex_pc if set, otherwise defaults to the 5th above key_root.
    Prefers the lowest pitch with the target pitch class that sits above the
    midpoint of the pitch range.
    """
    apex_pc = getattr(config, "apex_pc", None)

    if apex_pc is not None:
        target_pc = apex_pc % 12
        candidates = [(i, p) for i, p in enumerate(pitches) if p % 12 == target_pc]
        if candidates:
            mid_midi = (pitches[0] + pitches[-1]) / 2.0
            upper = [(i, p) for i, p in candidates if p >= mid_midi]
            if upper:
                return min(upper, key=lambda x: x[1])[0]
            return max(candidates, key=lambda x: x[1])[0]

    target_midi_apex = key_root + (octave_low + 1) * 12 + 7
    idx = min(range(len(pitches)), key=lambda i: abs(pitches[i] - target_midi_apex))
    if idx == root_idx:
        idx = min(len(pitches) - 1, len(pitches) // 2)
    return idx


class PhraseMelodyGenerator:
    """
    Phrase-grammar melody generator.
    Three archetypes:
      question — stepwise ascent to an apex (tension) tone
      answer   — stepwise descent back to the root
      pedal    — one pitch held rhythmically with neighbor-note ornaments
    """

    def generate_variation(
        self,
        chord_progression: list[tuple[int, float]],
        config,
        rng: np.random.Generator,
    ) -> list[tuple[int, float, int]]:

        key_root: int = config.key_root if config.key_root is not None else chord_progression[0][0]
        octave_low:  int = getattr(config, "octave_low",  4)
        octave_high: int = getattr(config, "octave_high", 5)

        pitches = get_scale_pitches(key_root, config.scale_mode, octave_low, octave_high)
        if not pitches:
            pitches = get_scale_pitches(key_root, "pentatonic_minor", octave_low, octave_high)

        n_pitches = len(pitches)
        if n_pitches == 0:
            return []

        total_beats = sum(dur for _, dur in chord_progression)
        phrase_beats = getattr(config, "phrase_length_beats", 4.0)
        n_phrases = max(1, round(total_beats / phrase_beats))

        # root_idx: pitch closest to key_root in the lower octave
        target_midi_root = key_root + octave_low * 12
        root_idx = min(range(n_pitches), key=lambda i: abs(pitches[i] - target_midi_root))

        apex_idx = _resolve_apex_idx(pitches, config, key_root, octave_low, root_idx)

        phrase_type  = getattr(config, "phrase_type",     "auto")
        phrase_types = _build_phrase_sequence(phrase_type, n_phrases, rng)
        rest_prob    = getattr(config, "rest_probability", 0.05)
        temperature  = float(getattr(config, "temperature",  0.5))
        syncopation  = getattr(config, "syncopation",  0.0)

        notes: list[tuple[int, float, int]] = []
        last_idx = root_idx

        for ptype in phrase_types:
            raw_template = RHYTHM_TEMPLATES[ptype][rng.integers(len(RHYTHM_TEMPLATES[ptype]))]
            rhythm = _scale_rhythm(raw_template, phrase_beats)
            n = len(rhythm)

            if ptype == "question":
                # In explicit "question" mode restart from root each phrase so
                # successive phrases don't get stuck ascending apex→apex.
                if phrase_type == "question":
                    last_idx = root_idx
                plan = _stepwise_path(pitches, last_idx, apex_idx, n)
                spread = max(1, apex_idx - root_idx)
                for planned_idx, dur in zip(plan, rhythm):
                    actual_idx = _temperature_pick(planned_idx, n_pitches, temperature, rng)
                    vel = _clamp(72 + int((actual_idx - root_idx) / spread * 18), 40, 120)
                    if rng.random() < rest_prob:
                        notes.append((-1, dur, 0))
                    else:
                        notes.append((pitches[actual_idx], dur, vel))
                last_idx = plan[-1]  # chain on the planned contour, not the temperature-smeared note

            elif ptype == "answer":
                # Ensure there is somewhere to descend from.
                if last_idx == root_idx:
                    last_idx = apex_idx
                plan = _stepwise_path(pitches, last_idx, root_idx, n)
                spread = max(1, apex_idx - root_idx)
                for planned_idx, dur in zip(plan, rhythm):
                    actual_idx = _temperature_pick(planned_idx, n_pitches, temperature, rng)
                    vel = _clamp(80 - int((actual_idx - root_idx) / spread * 12), 40, 120)
                    if rng.random() < rest_prob:
                        notes.append((-1, dur, 0))
                    else:
                        notes.append((pitches[actual_idx], dur, vel))
                last_idx = root_idx

            elif ptype == "pedal":
                pedal_idx = last_idx
                for k, dur in enumerate(rhythm):
                    vel = _clamp(72 + int(rng.integers(-8, 9)), 40, 120)
                    if rng.random() < rest_prob:
                        notes.append((-1, dur, 0))
                    else:
                        # Occasional neighbor-note ornament (not on the first note of the phrase).
                        # Temperature widens how far the ornament can stray.
                        if k > 0 and rng.random() < 0.30:
                            raw_neighbor = _clamp(
                                pedal_idx + int(rng.choice([-1, 1])),
                                0, n_pitches - 1,
                            )
                            actual_neighbor = _temperature_pick(raw_neighbor, n_pitches, temperature, rng)
                            notes.append((pitches[actual_neighbor], dur, vel - 6))
                        else:
                            notes.append((pitches[pedal_idx], dur, vel))
                # pedal_idx (and thus last_idx) stays put

        notes = _apply_syncopation(notes, syncopation, rng)

        motif_bars = getattr(config, "motif_bars", 4)
        if motif_bars > 0:
            motif_beats = min(motif_bars * 4.0, total_beats)
            motif = _trim_to_beats(notes, motif_beats)
            return _tile_notes(motif, total_beats)

        return _trim_to_beats(notes, total_beats)
