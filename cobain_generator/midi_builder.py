from __future__ import annotations
import mido
from mido import MidiFile, MidiTrack, Message, MetaMessage
from .config import ProgressionConfig, MidiBuilderConfig
from .scales import CHORD_INTERVALS

# GM drum note numbers
KICK   = 36
SNARE  = 38
HI_HAT_CLOSED = 42
HI_HAT_OPEN   = 46
RIDE   = 51


class MidiBuilder:
    """
    Assembles chord + melody + bass + drums into a multi-track MIDI file.

    Track layout:
      0: Tempo / time signature meta
      1: Power chords (root + fifth only — no thirds ever)
      2: Melody
      3: Bass root (optional)
      4: Drums (optional)

    IMPORTANT — mido uses delta-time (ticks since previous event IN THE SAME TRACK).
    Every _build_*_track method accumulates absolute_tick and emits correct deltas.
    """

    def __init__(self, prog_config: ProgressionConfig, builder_config: MidiBuilderConfig | None = None):
        self.prog = prog_config
        self.cfg = builder_config or MidiBuilderConfig()

    def _beats_to_ticks(self, beats: float) -> int:
        return int(round(beats * self.cfg.ticks_per_beat))

    def _tempo(self) -> int:
        return int(60_000_000 / self.prog.tempo_bpm)

    # ------------------------------------------------------------------
    # Meta track
    # ------------------------------------------------------------------
    def _build_meta_track(self) -> MidiTrack:
        track = MidiTrack()
        track.append(MetaMessage("set_tempo", tempo=self._tempo(), time=0))
        track.append(MetaMessage(
            "time_signature",
            numerator=self.prog.beats_per_bar,
            denominator=4,
            clocks_per_click=24,
            notated_32nd_notes_per_beat=8,
            time=0,
        ))
        track.append(MetaMessage("end_of_track", time=0))
        return track

    # ------------------------------------------------------------------
    # Chord track — power chords only (root + fifth)
    # ------------------------------------------------------------------
    def _build_chord_track(self, chord_progression: list[tuple[int, float]]) -> MidiTrack:
        track = MidiTrack()
        # Program change: overdriven guitar
        track.append(Message("program_change", channel=self.cfg.chord_channel,
                              program=self.cfg.chord_program, time=0))

        abs_tick = 0
        last_event_tick = 0

        for root_pc, duration_beats in chord_progression:
            dur_ticks = self._beats_to_ticks(duration_beats)
            root_midi = root_pc + 48     # octave 3
            fifth_midi = root_midi + 7

            # Note on — both root and fifth simultaneously
            delta = abs_tick - last_event_tick
            track.append(Message("note_on", channel=self.cfg.chord_channel,
                                  note=root_midi, velocity=self.cfg.chord_velocity, time=delta))
            track.append(Message("note_on", channel=self.cfg.chord_channel,
                                  note=fifth_midi, velocity=self.cfg.chord_velocity, time=0))
            last_event_tick = abs_tick

            # Note off — at end of chord duration
            abs_tick += dur_ticks
            delta = abs_tick - last_event_tick
            track.append(Message("note_off", channel=self.cfg.chord_channel,
                                  note=root_midi, velocity=0, time=delta))
            track.append(Message("note_off", channel=self.cfg.chord_channel,
                                  note=fifth_midi, velocity=0, time=0))
            last_event_tick = abs_tick

        track.append(MetaMessage("end_of_track", time=0))
        return track

    # ------------------------------------------------------------------
    # Melody track
    # ------------------------------------------------------------------
    def _build_melody_track(self, melody_notes: list[tuple[int, float, int]]) -> MidiTrack:
        track = MidiTrack()
        track.append(Message("program_change", channel=self.cfg.melody_channel,
                              program=self.cfg.melody_program, time=0))

        abs_tick = 0
        last_event_tick = 0

        for midi_pitch, duration_beats, velocity in melody_notes:
            dur_ticks = self._beats_to_ticks(duration_beats)

            if midi_pitch == -1:
                # Rest: just advance time, no note events
                abs_tick += dur_ticks
                continue

            # Note on
            delta = abs_tick - last_event_tick
            track.append(Message("note_on", channel=self.cfg.melody_channel,
                                  note=midi_pitch, velocity=velocity, time=delta))
            last_event_tick = abs_tick

            # Note off
            abs_tick += dur_ticks
            delta = abs_tick - last_event_tick
            track.append(Message("note_off", channel=self.cfg.melody_channel,
                                  note=midi_pitch, velocity=0, time=delta))
            last_event_tick = abs_tick

        track.append(MetaMessage("end_of_track", time=0))
        return track

    # ------------------------------------------------------------------
    # Bass track — root only, 2 octaves below chord, half duration
    # ------------------------------------------------------------------
    def _build_bass_track(self, chord_progression: list[tuple[int, float]]) -> MidiTrack:
        track = MidiTrack()
        track.append(Message("program_change", channel=self.cfg.bass_channel,
                              program=self.cfg.bass_program, time=0))

        abs_tick = 0
        last_event_tick = 0

        for root_pc, duration_beats in chord_progression:
            bass_midi = root_pc + 24   # octave 1
            note_dur = self._beats_to_ticks(duration_beats * 0.45)   # slightly shorter than chord
            rest_dur = self._beats_to_ticks(duration_beats) - note_dur

            delta = abs_tick - last_event_tick
            track.append(Message("note_on", channel=self.cfg.bass_channel,
                                  note=bass_midi, velocity=self.cfg.bass_velocity, time=delta))
            last_event_tick = abs_tick

            abs_tick += note_dur
            delta = abs_tick - last_event_tick
            track.append(Message("note_off", channel=self.cfg.bass_channel,
                                  note=bass_midi, velocity=0, time=delta))
            last_event_tick = abs_tick

            abs_tick += rest_dur

        track.append(MetaMessage("end_of_track", time=0))
        return track

    # ------------------------------------------------------------------
    # Drum track — standard 4/4 kick-snare-hat grunge beat
    # ------------------------------------------------------------------
    def _build_drum_track(self, total_beats: float) -> MidiTrack:
        """
        Pattern per bar (4 beats):
          beat 1.0: kick + closed hi-hat
          beat 1.5: closed hi-hat
          beat 2.0: snare + closed hi-hat
          beat 2.5: closed hi-hat
          beat 3.0: kick + closed hi-hat
          beat 3.5: closed hi-hat
          beat 4.0: snare + open hi-hat
          beat 4.5: closed hi-hat
        """
        track = MidiTrack()
        ch = self.cfg.drum_channel

        # Build one bar's worth of events as (beat_offset, note, vel, is_on) tuples
        bar_events: list[tuple[float, int, int, bool]] = []
        note_dur = 0.45  # beats — notes shorter than grid slot

        def add_hit(beat: float, note: int, vel: int = 80):
            bar_events.append((beat, note, vel, True))
            bar_events.append((beat + note_dur, note, 0, False))

        add_hit(0.0, KICK, 90)
        add_hit(0.0, HI_HAT_CLOSED, 70)
        add_hit(0.5, HI_HAT_CLOSED, 60)
        add_hit(1.0, SNARE, 85)
        add_hit(1.0, HI_HAT_CLOSED, 70)
        add_hit(1.5, HI_HAT_CLOSED, 60)
        add_hit(2.0, KICK, 90)
        add_hit(2.0, HI_HAT_CLOSED, 70)
        add_hit(2.5, HI_HAT_CLOSED, 60)
        add_hit(3.0, SNARE, 85)
        add_hit(3.0, HI_HAT_OPEN, 75)
        add_hit(3.5, HI_HAT_CLOSED, 60)

        bar_events.sort(key=lambda e: (e[0], not e[3]))  # sort by beat, on before off

        total_bars = int(total_beats / self.prog.beats_per_bar)
        abs_tick = 0
        last_event_tick = 0

        for bar in range(total_bars):
            bar_start_beats = bar * self.prog.beats_per_bar
            for beat_offset, note, vel, is_on in bar_events:
                event_tick = self._beats_to_ticks(bar_start_beats + beat_offset)
                delta = event_tick - last_event_tick
                msg_type = "note_on" if is_on else "note_off"
                track.append(Message(msg_type, channel=ch, note=note, velocity=vel, time=delta))
                last_event_tick = event_tick

        track.append(MetaMessage("end_of_track", time=0))
        return track

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------
    def build(
        self,
        chord_progression: list[tuple[int, float]],
        melody_notes: list[tuple[int, float, int]],
        output_path: str,
    ) -> str:
        total_beats = sum(d for _, d in chord_progression)
        mid = MidiFile(ticks_per_beat=self.cfg.ticks_per_beat)
        mid.tracks.append(self._build_meta_track())
        mid.tracks.append(self._build_chord_track(chord_progression))
        mid.tracks.append(self._build_melody_track(melody_notes))
        if self.cfg.include_bass:
            mid.tracks.append(self._build_bass_track(chord_progression))
        if self.cfg.include_drums:
            mid.tracks.append(self._build_drum_track(total_beats))
        mid.save(output_path)
        return output_path

    def build_song(
        self,
        sections: list,   # list of (SectionConfig, chord_prog, melody_notes)
        output_path: str,
    ) -> str:
        """
        Assemble a multi-section song into a single MIDI file.
        Sections are concatenated with correct delta-time accounting.
        Chord velocity scales per section for the dynamic arc.
        """
        mid = MidiFile(ticks_per_beat=self.cfg.ticks_per_beat)
        mid.tracks.append(self._build_meta_track())

        chord_track  = MidiTrack()
        melody_track = MidiTrack()
        bass_track   = MidiTrack()

        chord_track.append(Message("program_change", channel=self.cfg.chord_channel,
                                    program=self.cfg.chord_program, time=0))
        melody_track.append(Message("program_change", channel=self.cfg.melody_channel,
                                     program=self.cfg.melody_program, time=0))
        bass_track.append(Message("program_change", channel=self.cfg.bass_channel,
                                   program=self.cfg.bass_program, time=0))

        # Each track keeps its own absolute tick cursor and last-event tick
        chord_last  = 0
        melody_last = 0
        bass_last   = 0
        chord_cur   = 0   # absolute tick of next chord note_on
        melody_cur  = 0
        bass_cur    = 0

        for section, chord_prog, melody_notes in sections:
            chord_vel = max(1, min(127, int(self.cfg.chord_velocity * section.chord_velocity_scale)))
            bass_vel  = max(1, min(127, int(self.cfg.bass_velocity  * section.chord_velocity_scale)))

            # ── chord track ─────────────────────────────────────────────
            for root_pc, dur_beats in chord_prog:
                dur_ticks  = self._beats_to_ticks(dur_beats)
                root_midi  = root_pc + 48
                fifth_midi = root_midi + 7

                on_delta = chord_cur - chord_last
                chord_track.append(Message("note_on", channel=self.cfg.chord_channel,
                                            note=root_midi,  velocity=chord_vel, time=on_delta))
                chord_track.append(Message("note_on", channel=self.cfg.chord_channel,
                                            note=fifth_midi, velocity=chord_vel, time=0))
                chord_last = chord_cur

                chord_cur += dur_ticks
                off_delta = chord_cur - chord_last
                chord_track.append(Message("note_off", channel=self.cfg.chord_channel,
                                            note=root_midi,  velocity=0, time=off_delta))
                chord_track.append(Message("note_off", channel=self.cfg.chord_channel,
                                            note=fifth_midi, velocity=0, time=0))
                chord_last = chord_cur

            # ── melody track ─────────────────────────────────────────────
            for midi_pitch, dur_beats, velocity in melody_notes:
                dur_ticks = self._beats_to_ticks(dur_beats)
                if midi_pitch == -1:
                    melody_cur += dur_ticks
                    continue
                on_delta = melody_cur - melody_last
                melody_track.append(Message("note_on", channel=self.cfg.melody_channel,
                                             note=midi_pitch, velocity=velocity, time=on_delta))
                melody_last = melody_cur

                melody_cur += dur_ticks
                off_delta = melody_cur - melody_last
                melody_track.append(Message("note_off", channel=self.cfg.melody_channel,
                                             note=midi_pitch, velocity=0, time=off_delta))
                melody_last = melody_cur

            # ── bass track ───────────────────────────────────────────────
            if self.cfg.include_bass:
                for root_pc, dur_beats in chord_prog:
                    bass_midi  = root_pc + 24
                    note_ticks = self._beats_to_ticks(dur_beats * 0.45)
                    rest_ticks = self._beats_to_ticks(dur_beats) - note_ticks

                    on_delta = bass_cur - bass_last
                    bass_track.append(Message("note_on", channel=self.cfg.bass_channel,
                                               note=bass_midi, velocity=bass_vel, time=on_delta))
                    bass_last = bass_cur

                    bass_cur += note_ticks
                    off_delta = bass_cur - bass_last
                    bass_track.append(Message("note_off", channel=self.cfg.bass_channel,
                                               note=bass_midi, velocity=0, time=off_delta))
                    bass_last = bass_cur
                    bass_cur += rest_ticks

        chord_track.append(MetaMessage("end_of_track", time=0))
        melody_track.append(MetaMessage("end_of_track", time=0))
        bass_track.append(MetaMessage("end_of_track", time=0))

        mid.tracks.append(chord_track)
        mid.tracks.append(melody_track)
        if self.cfg.include_bass:
            mid.tracks.append(bass_track)

        mid.save(output_path)
        return output_path

    def build_diatonic(
        self,
        diatonic_progression: list[tuple[int, str, float]],
        melody_notes: list[tuple[int, float, int]],
        output_path: str,
    ) -> str:
        """Variant for comparison module: chords include thirds (major/minor/dim)."""
        total_beats = sum(d for _, _, d in diatonic_progression)
        mid = MidiFile(ticks_per_beat=self.cfg.ticks_per_beat)
        mid.tracks.append(self._build_meta_track())
        mid.tracks.append(self._build_diatonic_chord_track(diatonic_progression))
        mid.tracks.append(self._build_melody_track(melody_notes))
        if self.cfg.include_bass:
            bass_prog = [(r, d) for r, _, d in diatonic_progression]
            mid.tracks.append(self._build_bass_track(bass_prog))
        if self.cfg.include_drums:
            mid.tracks.append(self._build_drum_track(total_beats))
        mid.save(output_path)
        return output_path

    def _build_diatonic_chord_track(self, diatonic_progression: list[tuple[int, str, float]]) -> MidiTrack:
        track = MidiTrack()
        track.append(Message("program_change", channel=self.cfg.chord_channel,
                              program=24, time=0))  # GM: Acoustic Guitar (nylon)
        abs_tick = 0
        last_event_tick = 0

        for root_pc, quality, duration_beats in diatonic_progression:
            intervals = CHORD_INTERVALS.get(quality, CHORD_INTERVALS["major"])
            root_midi = root_pc + 48
            chord_notes = [root_midi + i for i in intervals]
            dur_ticks = self._beats_to_ticks(duration_beats)

            # All notes on
            delta = abs_tick - last_event_tick
            for i, note in enumerate(chord_notes):
                track.append(Message("note_on", channel=self.cfg.chord_channel,
                                      note=note, velocity=self.cfg.chord_velocity,
                                      time=delta if i == 0 else 0))
            last_event_tick = abs_tick

            # All notes off
            abs_tick += dur_ticks
            delta = abs_tick - last_event_tick
            for i, note in enumerate(chord_notes):
                track.append(Message("note_off", channel=self.cfg.chord_channel,
                                      note=note, velocity=0,
                                      time=delta if i == 0 else 0))
            last_event_tick = abs_tick

        track.append(MetaMessage("end_of_track", time=0))
        return track
