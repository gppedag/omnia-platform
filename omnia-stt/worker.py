import glob
import json
import logging
import os
import re
import subprocess
import tempfile
import time
from pathlib import Path

import psycopg2
import psycopg2.extras
import requests


logging.basicConfig(
    level=logging.INFO,
    format=(
        "%(asctime)s "
        "%(levelname)s "
        "%(message)s"
    ),
)

log = logging.getLogger(
    "omnia-stt"
)


DB_HOST = os.getenv(
    "POSTGRES_HOST",
    "postgres"
)

DB_PORT = int(
    os.getenv(
        "POSTGRES_PORT",
        "5432"
    )
)

DB_NAME = os.getenv(
    "POSTGRES_DB",
    "cup_system"
)

DB_USER = os.getenv(
    "POSTGRES_USER",
    "cup_admin"
)

DB_PASSWORD = os.getenv(
    "POSTGRES_PASSWORD",
    "changeme"
)

RECORDING_ROOT = Path(
    os.getenv(
        "OMNIA_RECORDING_ROOT",
        "/recordings"
    )
)

WHISPER_URL = os.getenv(
    "OMNIA_WHISPER_URL",
    "http://host.docker.internal:8090/inference"
)

POLL_SECONDS = int(
    os.getenv(
        "OMNIA_STT_POLL_SECONDS",
        "5"
    )
)

RECORDING_WAIT_SECONDS = int(
    os.getenv(
        "OMNIA_STT_RECORDING_WAIT_SECONDS",
        "120"
    )
)

MAX_ATTEMPTS = int(
    os.getenv(
        "OMNIA_STT_MAX_ATTEMPTS",
        "8"
    )
)


def db_connect():

    return psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
    )


def run(cmd):

    result = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=True,
    )

    return result.stdout.strip()


def ffprobe_duration(path):

    try:

        value = run([
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=nw=1:nk=1",
            str(path),
        ])

        return float(value)

    except Exception:

        return 0.0


def recording_prefix(value):

    if not value:
        return None

    value = str(value).strip()

    m = re.match(
        r"^(mikopbx-\d+)",
        value
    )

    if m:
        return m.group(1)

    return None


def find_recording(call):

    prefixes = []

    for value in (
        call.get("asterisk_uniqueid"),
        call.get("asterisk_linkedid"),
    ):

        prefix = recording_prefix(
            value
        )

        if (
            prefix
            and prefix not in prefixes
        ):
            prefixes.append(prefix)


    candidates = []

    for prefix in prefixes:

        pattern = str(
            RECORDING_ROOT
            / "**"
            / f"{prefix}*.webm"
        )

        candidates.extend(
            glob.glob(
                pattern,
                recursive=True,
            )
        )


    candidates = list(
        dict.fromkeys(candidates)
    )


    if not candidates:

        return None


    scored = []

    for filename in candidates:

        duration = ffprobe_duration(
            filename
        )

        try:
            size = os.path.getsize(
                filename
            )
        except OSError:
            size = 0

        scored.append(
            (
                duration,
                size,
                filename,
            )
        )


    scored.sort(
        reverse=True
    )

    # MikoPBX può generare più WebM
    # per la stessa famiglia UniqueID.
    # Per la telefonata completa scegliamo
    # quello con durata maggiore.
    return scored[0][2]


def split_channels(
    recording,
    directory,
):

    patient = (
        Path(directory)
        / "patient.wav"
    )

    operator = (
        Path(directory)
        / "operator.wav"
    )


    # LEFT = Paziente
    run([
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(recording),
        "-af",
        "pan=mono|c0=c0",
        "-ar",
        "16000",
        "-ac",
        "1",
        str(patient),
    ])


    # RIGHT = Operatore
    run([
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(recording),
        "-af",
        "pan=mono|c0=c1",
        "-ar",
        "16000",
        "-ac",
        "1",
        str(operator),
    ])


    return (
        patient,
        operator,
    )



# OMNIA_STT_VAD_V2

def detect_speech_regions(path):
    """
    Individua le zone non silenziose prima di Whisper.

    FFmpeg silencedetect:
      noise=-38dB
      duration=0.55s

    Restituisce:
      [(start_sec, end_sec), ...]
    """

    duration = ffprobe_duration(path)

    if duration <= 0:
        return []

    proc = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-i",
            str(path),
            "-af",
            "silencedetect=noise=-38dB:d=0.55",
            "-f",
            "null",
            "-",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )

    text = proc.stderr

    silence_starts = [
        float(x)
        for x in re.findall(
            r"silence_start:\s*([0-9.]+)",
            text
        )
    ]

    silence_ends = [
        float(x)
        for x in re.findall(
            r"silence_end:\s*([0-9.]+)",
            text
        )
    ]

    silences = []

    for i, start in enumerate(silence_starts):

        if i < len(silence_ends):
            end = silence_ends[i]
        else:
            end = duration

        if end > start:
            silences.append(
                (
                    max(0.0, start),
                    min(duration, end),
                )
            )

    # Nessun silenzio rilevato:
    # consideriamo tutto il file parlato.
    if not silences:
        return [(0.0, duration)]

    regions = []
    cursor = 0.0

    for start, end in silences:

        if start > cursor:
            regions.append(
                (
                    cursor,
                    start,
                )
            )

        cursor = max(
            cursor,
            end
        )

    if cursor < duration:
        regions.append(
            (
                cursor,
                duration,
            )
        )

    # Margine piccolo intorno alla voce per non
    # troncare consonanti e attacchi.
    padded = []

    for start, end in regions:

        start = max(
            0.0,
            start - 0.20
        )

        end = min(
            duration,
            end + 0.25
        )

        # Scartiamo rumori brevissimi.
        if end - start < 0.35:
            continue

        if padded and (
            start - padded[-1][1]
        ) < 0.30:

            padded[-1] = (
                padded[-1][0],
                end,
            )

        else:
            padded.append(
                (start, end)
            )

    return padded


def rms_db(path):
    """
    Stima semplice dell'energia media del WAV.
    Serve come secondo filtro contro Whisper
    su tracce praticamente mute.
    """

    proc = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-i",
            str(path),
            "-af",
            "volumedetect",
            "-f",
            "null",
            "-",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )

    match = re.search(
        r"mean_volume:\s*(-?[0-9.]+)\s*dB",
        proc.stderr
    )

    if not match:
        return -100.0

    try:
        return float(
            match.group(1)
        )
    except Exception:
        return -100.0


def extract_region(
    source,
    destination,
    start,
    end,
):
    run([
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-ss",
        f"{start:.3f}",
        "-to",
        f"{end:.3f}",
        "-i",
        str(source),
        "-ar",
        "16000",
        "-ac",
        "1",
        str(destination),
    ])


def whisper_request_raw(path):

    def send(
        response_format
    ):

        with open(
            path,
            "rb"
        ) as handle:

            response = requests.post(
                WHISPER_URL,
                files={
                    "file": (
                        Path(path).name,
                        handle,
                        "audio/wav",
                    )
                },
                data={
                    "language": "it",
                    "response_format":
                        response_format,
                },
                timeout=180,
            )

        response.raise_for_status()

        return response.json()


    # Proviamo prima il formato
    # con timestamp.
    try:

        data = send(
            "verbose_json"
        )

    except Exception:

        data = send(
            "json"
        )


    text = (
        data.get("text")
        if isinstance(data, dict)
        else None
    ) or ""


    segments = []

    if isinstance(data, dict):

        raw_segments = data.get(
            "segments"
        )

        if isinstance(
            raw_segments,
            list
        ):

            for seg in raw_segments:

                content = str(
                    seg.get(
                        "text",
                        ""
                    )
                ).strip()

                if not content:
                    continue


                start = seg.get(
                    "start",
                    0
                )

                end = seg.get(
                    "end",
                    start
                )


                try:
                    start_ms = int(
                        float(start) * 1000
                    )

                    end_ms = int(
                        float(end) * 1000
                    )

                except Exception:
                    start_ms = 0
                    end_ms = 0


                segments.append({
                    "content":
                        content,

                    "started_ms":
                        start_ms,

                    "ended_ms":
                        end_ms,

                    "confidence":
                        None,
                })


    # whisper.cpp della DGX può
    # restituire soltanto {"text": "..."}.
    if not segments:

        content = text.strip()

        if content:

            duration_ms = int(
                ffprobe_duration(path)
                * 1000
            )

            segments.append({
                "content":
                    content,

                "started_ms":
                    0,

                "ended_ms":
                    duration_ms,

                "confidence":
                    None,
            })


    return segments



def whisper_request(path):
    """
    Trascrive esclusivamente le zone con voce.
    Mantiene i timestamp relativi alla Call.
    """

    regions = detect_speech_regions(
        path
    )

    if not regions:

        log.info(
            "Nessuna voce rilevata in %s",
            path,
        )

        return []


    total_speech = sum(
        end - start
        for start, end in regions
    )

    duration = ffprobe_duration(
        path
    )


    log.info(
        "VAD %s: %.2fs voce / %.2fs audio, %d regioni",
        Path(path).name,
        total_speech,
        duration,
        len(regions),
    )


    # Traccia estremamente debole:
    # evitiamo direttamente Whisper.
    energy = rms_db(path)

    if energy < -48.0:

        log.info(
            "Skip STT %s: mean %.1f dB",
            Path(path).name,
            energy,
        )

        return []


    results = []

    with tempfile.TemporaryDirectory(
        prefix="omnia-vad-"
    ) as tempdir:

        for index, (
            region_start,
            region_end,
        ) in enumerate(regions):

            chunk = (
                Path(tempdir)
                / f"speech-{index}.wav"
            )

            extract_region(
                path,
                chunk,
                region_start,
                region_end,
            )


            # Un ulteriore controllo sul singolo
            # pezzo evita click/rumori scambiati
            # per parlato.
            chunk_energy = rms_db(
                chunk
            )

            if chunk_energy < -45.0:
                continue


            segments = (
                whisper_request_raw(
                    chunk
                )
            )


            offset_ms = int(
                region_start * 1000
            )


            for seg in segments:

                content = str(
                    seg.get(
                        "content",
                        ""
                    )
                ).strip()

                if not content:
                    continue


                # Filtri conservativi per alcune
                # allucinazioni tipiche di Whisper
                # su silenzio.
                normalized = (
                    content
                    .lower()
                    .strip(" .,!?:;")
                )

                hallucinations = {
                    "grazie a tutti",
                    "grazie per l'attenzione",
                    "sottotitoli e revisione a cura di qtss",
                    "sottotitoli creati dalla comunità amara.org",
                }

                if normalized in hallucinations:
                    continue


                results.append({
                    "content":
                        content,

                    "started_ms":
                        offset_ms
                        + int(
                            seg.get(
                                "started_ms",
                                0
                            )
                        ),

                    "ended_ms":
                        offset_ms
                        + int(
                            seg.get(
                                "ended_ms",
                                0
                            )
                        ),

                    "confidence":
                        seg.get(
                            "confidence"
                        ),
                })


    return results


def claim_call(conn):

    with conn.cursor(
        cursor_factory=
        psycopg2.extras.RealDictCursor
    ) as cur:

        cur.execute("""
            SELECT
                c.id,
                c.caller_number,
                c.callee_number,
                c.call_type,
                c.operator_extension,
                c.status,
                c.started_at,
                c.answered_at,
                c.ended_at,
                c.duration_seconds,
                c.asterisk_uniqueid,
                c.asterisk_linkedid,
                COALESCE(
                    j.status,
                    'pending'
                ) AS transcription_status,
                COALESCE(
                    j.attempts,
                    0
                ) AS attempts
            FROM calls c
            LEFT JOIN
                call_transcription_jobs j
                ON j.call_id=c.id
            WHERE
                c.call_type='operator'
                AND c.status='ended'
                AND c.ended_at IS NOT NULL
                AND COALESCE(
                    j.status,
                    'pending'
                )
                NOT IN (
                    'completed',
                    'processing'
                )
                AND COALESCE(
                    j.attempts,
                    0
                ) < %s
            ORDER BY
                c.id DESC
            LIMIT 1
        """, (
            MAX_ATTEMPTS,
        ))

        row = cur.fetchone()

        if not row:
            return None


        cur.execute("""
            INSERT INTO
                call_transcription_jobs (
                    call_id,
                    status,
                    attempts,
                    started_at,
                    updated_at
                )
            VALUES (
                %s,
                'processing',
                1,
                NOW(),
                NOW()
            )
            ON CONFLICT (call_id)
            DO UPDATE SET
                status='processing',
                attempts=
                    call_transcription_jobs
                    .attempts + 1,
                started_at=NOW(),
                updated_at=NOW(),
                last_error=NULL
        """, (
            row["id"],
        ))

        conn.commit()

        return dict(row)


def mark_failed(
    conn,
    call_id,
    error,
    status="failed",
):

    with conn.cursor() as cur:

        cur.execute("""
            UPDATE
                call_transcription_jobs
            SET
                status=%s,
                last_error=%s,
                updated_at=NOW()
            WHERE
                call_id=%s
        """, (
            status,
            str(error)[:4000],
            call_id,
        ))

    conn.commit()


def save_transcript(
    conn,
    call,
    recording,
    patient_segments,
    operator_segments,
):

    rows = []

    for speaker, segments in (
        (
            "patient",
            patient_segments,
        ),
        (
            "operator",
            operator_segments,
        ),
    ):

        for seg in segments:

            content = (
                seg["content"]
                .strip()
            )

            if not content:
                continue

            rows.append({
                "speaker":
                    speaker,

                "content":
                    content,

                "started_ms":
                    int(
                        seg.get(
                            "started_ms",
                            0
                        )
                    ),

                "ended_ms":
                    int(
                        seg.get(
                            "ended_ms",
                            0
                        )
                    ),

                "confidence":
                    seg.get(
                        "confidence"
                    ),
            })


    rows.sort(
        key=lambda x: (
            x["started_ms"],
            0
            if x["speaker"]
               == "patient"
            else 1,
        )
    )


    with conn.cursor() as cur:

        cur.execute("""
            DELETE FROM
                call_transcript_segments
            WHERE
                call_id=%s
        """, (
            call["id"],
        ))


        for row in rows:

            cur.execute("""
                INSERT INTO
                    call_transcript_segments (
                        call_id,
                        speaker,
                        content,
                        started_ms,
                        ended_ms,
                        confidence,
                        source
                    )
                VALUES (
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    'whisper_cpp'
                )
            """, (
                call["id"],
                row["speaker"],
                row["content"],
                row["started_ms"],
                row["ended_ms"],
                row["confidence"],
            ))


        cur.execute("""
            UPDATE
                call_transcription_jobs
            SET
                status='completed',
                recording_path=%s,
                completed_at=NOW(),
                updated_at=NOW(),
                last_error=NULL
            WHERE
                call_id=%s
        """, (
            str(recording),
            call["id"],
        ))


    conn.commit()


def process_call(
    conn,
    call,
):

    call_id = call["id"]

    log.info(
        "Call %s: ricerca registrazione",
        call_id,
    )


    recording = None

    deadline = (
        time.time()
        + RECORDING_WAIT_SECONDS
    )


    while (
        time.time()
        < deadline
    ):

        recording = find_recording(
            call
        )

        if recording:
            break

        time.sleep(3)


    if not recording:

        raise FileNotFoundError(
            "registrazione MikoPBX "
            "non trovata"
        )


    log.info(
        "Call %s: recording %s",
        call_id,
        recording,
    )


    with tempfile.TemporaryDirectory(
        prefix=f"omnia-call-{call_id}-"
    ) as tempdir:

        patient_wav, operator_wav = (
            split_channels(
                recording,
                tempdir,
            )
        )


        log.info(
            "Call %s: STT paziente",
            call_id,
        )

        patient_segments = (
            whisper_request(
                patient_wav
            )
        )


        log.info(
            "Call %s: STT operatore",
            call_id,
        )

        operator_segments = (
            whisper_request(
                operator_wav
            )
        )


        save_transcript(
            conn,
            call,
            recording,
            patient_segments,
            operator_segments,
        )


    log.info(
        "Call %s: trascrizione completata",
        call_id,
    )


def main():

    log.info(
        "OMNIA_STT_V1 avviato"
    )

    log.info(
        "Recording root: %s",
        RECORDING_ROOT,
    )

    log.info(
        "Whisper: %s",
        WHISPER_URL,
    )


    while True:

        conn = None

        try:

            conn = db_connect()

            call = claim_call(
                conn
            )

            if not call:

                conn.close()
                time.sleep(
                    POLL_SECONDS
                )
                continue


            try:

                process_call(
                    conn,
                    call,
                )

            except FileNotFoundError as exc:

                log.warning(
                    "Call %s: %s",
                    call["id"],
                    exc,
                )

                mark_failed(
                    conn,
                    call["id"],
                    exc,
                    "recording_not_found",
                )


            except Exception as exc:

                log.exception(
                    "Call %s: errore STT",
                    call["id"],
                )

                mark_failed(
                    conn,
                    call["id"],
                    exc,
                )


            conn.close()


        except Exception:

            log.exception(
                "Errore loop STT"
            )

            if conn:

                try:
                    conn.close()
                except Exception:
                    pass

            time.sleep(5)


if __name__ == "__main__":
    main()
