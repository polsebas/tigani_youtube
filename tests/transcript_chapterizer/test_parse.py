"""Parser UTF-8 y adaptador de archivo. Sin red y sin agente."""

from pathlib import Path

import pytest

from tigani_broadcast.transcript_chapterizer.models import Cue
from tigani_broadcast.transcript_chapterizer.parse import (
    FileTranscriptSource,
    TranscriptFormatError,
    parse_transcript,
)
from tigani_broadcast.transcript_chapterizer.source import TranscriptSource

FIXTURE = Path(__file__).parents[1] / "fixtures" / "transcripcion_breve.txt"

EXPECTED = [
    (0, "00:00:01", "Buen día, bienvenidos a un nuevo análisis de la coyuntura."),
    (1, "00:00:06", "Hoy el tema es la inflación de marzo y lo que publicó el Banco Central."),
    (2, "00:00:14", "El índice fue del 4,2 por ciento."),
    (3, "00:00:14", "Ese número es el que vamos a mirar con cuidado."),
    (4, "00:00:21", "El Banco Central publicó el dato el viernes."),
    (5, "00:01:03", "En el próximo tramo me detengo en las reservas."),
]


def _as_tuples(cues: list[Cue]) -> list[tuple[int, str, str]]:
    return [(cue.cue_index, cue.timestamp, cue.text) for cue in cues]


def test_fixture_conserva_orden_timestamps_y_texto() -> None:
    cues = FileTranscriptSource(FIXTURE).load()

    assert isinstance(FileTranscriptSource(FIXTURE), TranscriptSource)
    assert _as_tuples(cues) == EXPECTED
    assert cues[2].timestamp == cues[3].timestamp
    assert cues[4].timestamp < cues[5].timestamp


def test_archivo_sin_cues_validas_falla(tmp_path: Path) -> None:
    vacio = tmp_path / "vacio.txt"
    vacio.write_text("", encoding="utf-8")
    en_blanco = tmp_path / "blanco.txt"
    en_blanco.write_text("\n   \n\t\n", encoding="utf-8")

    for path in (vacio, en_blanco):
        with pytest.raises(TranscriptFormatError, match="no contiene ninguna cue") as exc_info:
            FileTranscriptSource(path).load()
        assert exc_info.value.line_number is None


@pytest.mark.parametrize(
    ("text", "fragmento"),
    [
        ("00:00:01 texto sin corchetes", "formato inválido"),
        ("[01:23] solo minutos y segundos", "formato inválido"),
        ("[00:00:01.500] con milisegundos", "formato inválido"),
        ("00:00:01,000 --> 00:00:04,000", "formato inválido"),
        ("  [00:00:01] con sangría", "formato inválido"),
    ],
)
def test_formato_invalido_indica_la_linea(text: str, fragmento: str) -> None:
    with pytest.raises(TranscriptFormatError, match=rf"línea 1: {fragmento}") as exc_info:
        parse_transcript(text)
    assert exc_info.value.line_number == 1


def test_el_numero_de_linea_cuenta_las_lineas_en_blanco() -> None:
    text = "\n\n[00:65:00] este reloj no existe\n"

    with pytest.raises(
        TranscriptFormatError, match=r"línea 3: timestamp fuera de rango: 00:65:00"
    ) as exc_info:
        parse_transcript(text)

    assert exc_info.value.line_number == 3


def test_segundos_fuera_de_rango() -> None:
    with pytest.raises(TranscriptFormatError, match=r"línea 1: timestamp fuera de rango: 00:00:60"):
        parse_transcript("[00:00:60] se pasó el segundo")


@pytest.mark.parametrize("text", ["[00:00:01]", "[00:00:01]   \t"])
def test_texto_vacio_tras_el_timestamp(text: str) -> None:
    with pytest.raises(
        TranscriptFormatError, match=r"línea 1: el texto de la cue está vacío"
    ) as exc_info:
        parse_transcript(text)
    assert exc_info.value.line_number == 1


def test_timestamp_que_retrocede_indica_la_linea_de_la_cue_nueva() -> None:
    text = "[00:00:10] primero\n[00:00:09] después\n"

    with pytest.raises(
        TranscriptFormatError,
        match=r"línea 2: el timestamp 00:00:09 retrocede respecto de 00:00:10",
    ) as exc_info:
        parse_transcript(text)

    assert exc_info.value.line_number == 2


def test_el_mismo_timestamp_y_un_salto_hacia_adelante_se_aceptan() -> None:
    text = (
        "[00:59:59] cierre del minuto\n"
        "[00:59:59] sigue en el mismo instante\n"
        "[01:00:00] minuto nuevo\n"
    )

    cues = parse_transcript(text)

    assert [cue.timestamp for cue in cues] == ["00:59:59", "00:59:59", "01:00:00"]
    assert [cue.cue_index for cue in cues] == [0, 1, 2]


def test_hora_de_un_digito_se_guarda_con_dos_y_las_mayores_de_99_quedan_completas() -> None:
    text = "[1:02:03] arranque\n[100:00:00] mucho después\n"

    cues = parse_transcript(text)

    assert [cue.timestamp for cue in cues] == ["01:02:03", "100:00:00"]


def test_retroceso_de_100_horas_a_99_no_se_juzga_como_texto() -> None:
    text = "[100:00:00] primero\n[99:00:00] esto es anterior\n"

    with pytest.raises(
        TranscriptFormatError,
        match=r"línea 2: el timestamp 99:00:00 retrocede respecto de 100:00:00",
    ):
        parse_transcript(text)


def test_avanza_de_99_horas_a_100() -> None:
    cues = parse_transcript("[99:00:00] antes\n[100:00:00] después\n")

    assert [cue.timestamp for cue in cues] == ["99:00:00", "100:00:00"]


def test_limpia_bordes_y_conserva_espacios_internos() -> None:
    cues = parse_transcript("[00:00:08]   el  4,2 por ciento   \n")

    assert cues[0].text == "el  4,2 por ciento"


def test_crlf_y_bom_no_cambian_las_cues() -> None:
    text = "\ufeff[00:00:01] primera línea\r\n\r\n[00:00:02] segunda línea\r\n"

    cues = parse_transcript(text)

    assert _as_tuples(cues) == [
        (0, "00:00:01", "primera línea"),
        (1, "00:00:02", "segunda línea"),
    ]


def test_bom_en_el_archivo_se_descarta(tmp_path: Path) -> None:
    path = tmp_path / "con-bom.txt"
    path.write_bytes("[00:00:04] con marca inicial\n".encode("utf-8-sig"))

    cues = FileTranscriptSource(path).load()

    assert cues[0].text == "con marca inicial"
    assert cues[0].timestamp == "00:00:04"


def test_utf8_invalido_falla_sin_linea(tmp_path: Path) -> None:
    path = tmp_path / "roto.txt"
    path.write_bytes(b"\xff\xfe[00:00:01] no es utf-8\n")

    with pytest.raises(TranscriptFormatError, match="no es UTF-8 válido") as exc_info:
        FileTranscriptSource(path).load()

    assert exc_info.value.line_number is None


def test_archivo_inexistente_falla_sin_linea(tmp_path: Path) -> None:
    path = tmp_path / "no-esta.txt"

    with pytest.raises(TranscriptFormatError, match="no se pudo leer el archivo") as exc_info:
        FileTranscriptSource(path).load()

    assert exc_info.value.line_number is None
    assert str(path) in str(exc_info.value)


def test_parsea_volcado_de_accesibilidad_de_youtube() -> None:
    text = (
        "0:000 secondsHola, amigos.\n"
        "1:021 minute, 2 secondsotra, pega en el travesaño.\n"
        "5:015 minutes, 1 second¿Sabes lo que son 3300 palos?\n"
    )
    cues = parse_transcript(text)
    assert [(cue.timestamp, cue.text) for cue in cues] == [
        ("00:00:00", "Hola, amigos."),
        ("00:01:02", "otra, pega en el travesaño."),
        ("00:05:01", "¿Sabes lo que son 3300 palos?"),
    ]


def test_una_linea_rota_no_devuelve_las_cues_anteriores() -> None:
    text = "[00:00:01] esta sí\nesto no es una cue\n"

    with pytest.raises(TranscriptFormatError, match="línea 2: formato inválido"):
        parse_transcript(text)


def test_el_protocolo_tambien_lo_cumple_un_doble_en_memoria() -> None:
    class _FuenteEnMemoria:
        def load(self) -> list[Cue]:
            return [Cue(cue_index=0, timestamp="00:00:01", text="en memoria")]

    fuente: TranscriptSource = _FuenteEnMemoria()

    assert isinstance(fuente, TranscriptSource)
    assert fuente.load()[0].text == "en memoria"
