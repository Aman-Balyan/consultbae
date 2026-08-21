"""
audio_utils.py
Extracts the required audio properties from any uploaded/recorded audio file:
duration, sample rate, bitrate, loudness (dB), plus a bonus rough noise/quality estimate.

Uses pydub (which shells out to ffmpeg) so it can decode whatever format the
browser's MediaRecorder produces (typically webm/opus or ogg/opus), not just wav.

NOTE on "bitrate": true bitrate is a property of the *compressed* source file,
which pydub/ffmpeg don't expose directly after decoding to raw PCM. We
approximate it as (file_size_in_bits / duration_in_seconds), which is the
standard way to estimate effective bitrate when you only have the decoded
audio + original file size. This is documented here and in the data issues
report as an approximation, not an exact codec-reported bitrate.
"""
import os
from pydub import AudioSegment
from pydub.silence import detect_silence


def analyze_audio(filepath):
    """Returns a dict with duration_sec, sample_rate_hz, bitrate_kbps,
    loudness_db, quality_note. Raises RuntimeError with a clear message if
    the file can't be decoded (e.g. corrupt upload, unsupported codec).
    """
    try:
        audio = AudioSegment.from_file(filepath)
    except Exception as e:
        raise RuntimeError(f"Could not decode audio file: {e}")

    duration_sec = len(audio) / 1000.0
    sample_rate_hz = audio.frame_rate

    file_size_bytes = os.path.getsize(filepath)
    bitrate_kbps = round((file_size_bytes * 8) / duration_sec / 1000, 1) if duration_sec > 0 else None

    # dBFS = decibels relative to full scale; pydub's standard loudness measure.
    # Silence/near-silence can produce -inf, guard against that for JSON/DB storage.
    loudness_db = audio.dBFS
    if loudness_db == float("-inf"):
        loudness_db = None

    quality_note = _rough_quality_estimate(audio, loudness_db)

    return {
        "duration_sec": round(duration_sec, 2),
        "sample_rate_hz": sample_rate_hz,
        "bitrate_kbps": bitrate_kbps,
        "loudness_db": round(loudness_db, 1) if loudness_db is not None else None,
        "quality_note": quality_note,
    }


def _rough_quality_estimate(audio, loudness_db):
    """BONUS: a rough, heuristic noise/quality flag -- not a real acoustic
    measurement. Two simple signals:
      1. Overall loudness bucket (too quiet / normal / possibly clipping)
      2. Silence ratio (how much of the clip is near-silent) as a proxy for
         dead air / bad mic pickup / stalled recordings
    Documented as an approximation, good enough to flag obviously bad
    submissions for a human to re-check, not a substitute for real DSP.
    """
    if loudness_db is None:
        return "silent or unmeasurable"

    if loudness_db > -3:
        loud_flag = "possibly clipping (very loud)"
    elif loudness_db < -35:
        loud_flag = "very quiet, may be low-quality mic or noisy environment"
    else:
        loud_flag = "normal loudness range"

    try:
        silent_ranges = detect_silence(audio, min_silence_len=500, silence_thresh=audio.dBFS - 16)
        silence_ms = sum(end - start for start, end in silent_ranges)
        silence_ratio = silence_ms / len(audio) if len(audio) > 0 else 0
    except Exception:
        silence_ratio = None

    if silence_ratio is not None and silence_ratio > 0.6:
        return f"{loud_flag}; {silence_ratio:.0%} of clip is silence -- check recording"
    return loud_flag


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python3 audio_utils.py <path_to_audio_file>")
        sys.exit(1)
    result = analyze_audio(sys.argv[1])
    for k, v in result.items():
        print(f"{k}: {v}")
