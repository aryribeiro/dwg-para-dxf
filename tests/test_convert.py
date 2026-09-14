"""Testes do conversor DWG -> DXF.

Rodam fora do Streamlit (modo "bare"): os st.* viram avisos inofensivos.
Precisam do dwg2dxf em bin/ (Linux: bin/dwg2dxf do repo; Windows: bin/dwg2dxf.exe).
"""
import sys
import zlib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import app  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"
OUTPUT = Path(__file__).parent / "output"


def reler(dxf_bytes: bytes, tmp_path: Path, nome="entregue.dxf"):
    """Relê o arquivo entregue com o leitor ESTRITO do ezdxf (readfile, não
    recover). É a prova de que o DXF abre em qualquer leitor que siga a
    especificação; o modo de recuperação aceitaria arquivos que o AutoCAD
    recusa."""
    import ezdxf
    p = tmp_path / nome
    p.write_bytes(dxf_bytes)
    return ezdxf.readfile(p)


# --- inspeção do cabeçalho -------------------------------------------------

def test_header_dwg_2018():
    data = (FIXTURES / "sample_2018.dwg").read_bytes()
    assert app.inspect_header(data) == ("dwg", "2018")


def test_header_dwg_2000():
    data = (FIXTURES / "Leader_2000.dwg").read_bytes()
    assert app.inspect_header(data) == ("dwg", "2000")


def test_header_dxf_renomeado():
    data = b"  0\r\nSECTION\r\n  2\r\nHEADER\r\n  0\r\nENDSEC\r\n  0\r\nEOF\r\n"
    assert app.inspect_header(data)[0] == "dxf"


def test_header_impostores():
    assert app.inspect_header(b"%PDF-1.7 lixo")[0] == "outro"
    assert app.inspect_header(b"PK\x03\x04" + b"\x00" * 40)[0] == "outro"
    assert app.inspect_header(b"")[0] == "outro"


# --- avisos do LibreDWG ----------------------------------------------------

def test_resumo_de_avisos():
    stderr = (
        "Warning: Unstable Class object 506 MATERIAL (0x481) 67/AF\n"
        "Warning: Unhandled Object TABLESTYLE in out_dxf 101/D1\n"
        "Warning: Unknown object, skipping eed/reactors/xdic\n"
        "Warning: Unknown object, skipping eed/reactors/xdic\n"
        "Warning: Skip CELLSTYLEMAP\n"
        "Warning: Skip TABLEGEOMETRY\n"
        "Warning: Unhandled Object ACAD_TABLE in out_dxf 120/F0\n"
        "Warning: Skip HATCH common handles due to short handle stream\n"
    )
    unknown, classes = app.summarize_libredwg_warnings(stderr)
    assert unknown == 2
    # estilos/materiais não entram; "Skip HATCH common handles" não é perda
    # da hachura; tabela e geometria de tabela entram
    assert classes == ["ACAD_TABLE", "TABLEGEOMETRY"]


# --- reparo do DXF desalinhado ---------------------------------------------

def quebrar_dxf(tmp_path: Path, nome="quebrado.dxf"):
    """Reproduz o defeito do LibreDWG: um valor de texto com quebra de linha
    no meio desalinha código/valor a partir dali. Devolve o caminho."""
    import ezdxf
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    msp.add_line((0, 0), (10, 0))
    msp.add_text("FICM").dxf.insert = (0, 5)
    msp.add_circle((5, 5), 2)
    bom = tmp_path / "bom.dxf"
    doc.saveas(bom)
    text = bom.read_text(encoding="utf-8")
    assert text.count("\nFICM\n") == 1
    quebrado = tmp_path / nome
    quebrado.write_text(text.replace("\nFICM\n", "\nFICM: Electric\nlixo\n", 1),
                        encoding="utf-8")
    return quebrado


def test_reparo_de_valor_com_quebra_de_linha(tmp_path):
    import ezdxf
    quebrado = quebrar_dxf(tmp_path)
    with pytest.raises(Exception):
        ezdxf.readfile(quebrado)
    fixed, repairs = app.read_dxf_with_repair(quebrado)
    assert repairs == 1
    assert len(fixed.modelspace()) == 3


def test_o_dxf_entregue_abre_limpo_depois_do_reparo(tmp_path):
    """A prova que dá razão ao app: o arquivo que entra não abre no leitor
    estrito, o que sai abre — e com o desenho inteiro."""
    import ezdxf
    quebrado = quebrar_dxf(tmp_path, "quebrado.dwg")
    with pytest.raises(Exception):
        ezdxf.readfile(quebrado)

    dxf_bytes, preview, info = app.convert_dwg_to_dxf(str(quebrado))
    assert info["repairs"] == 1
    assert info["dwgversion"] == "DXF renomeado"

    doc = reler(dxf_bytes, tmp_path)
    tipos = sorted(e.dxftype() for e in doc.modelspace())
    assert tipos == ["CIRCLE", "LINE", "TEXT"]
    assert doc.dxfversion == "AC1024"          # R2010 preservada
    assert preview is not None


# --- página virtual da prévia ----------------------------------------------

def test_pagina_lado_maior_e_piso():
    page, dpi = app.page_for_extents(1000.0, 500.0)
    assert round(page.width_in_mm) == 254
    assert round(page.height_in_mm) == 127
    assert dpi == 160
    page, _ = app.page_for_extents(10000.0, 1.0)
    assert page.height_in_mm >= app.PREVIEW_MIN_SIDE_PX / dpi * 25.4 - 0.1


# --- conversão de ponta a ponta -------------------------------------------

# Versão do DXF esperada na saída e entidades que o LibreDWG entrega ocas.
# Medido nas três fixtures; ver o comentário de sanitize_dxf sobre ACIS.
ESPERADO = {
    "sample_2018.dwg": ("AC1032", {}),
    "example_2018.dwg": ("AC1032", {"REGION": 2, "3DSOLID": 1}),
    "Leader_2000.dwg": ("AC1015", {}),
}


@pytest.mark.skipif(app.find_dwg2dxf() is None, reason="dwg2dxf ausente em bin/")
@pytest.mark.parametrize("name", list(ESPERADO))
def test_dwg_para_dxf(name, tmp_path):
    versao, perdidas = ESPERADO[name]
    OUTPUT.mkdir(exist_ok=True)
    dxf_bytes, preview, info = app.convert_dwg_to_dxf(str(FIXTURES / name))
    (OUTPUT / (Path(name).stem + ".dxf")).write_bytes(dxf_bytes)

    # 1. o arquivo entregue abre no leitor estrito
    doc = reler(dxf_bytes, tmp_path)

    # 2. a versão do DXF de origem foi preservada
    assert doc.dxfversion == versao == info["dxfversion"]

    # 3. nada de desenho se perdeu na reescrita, tirando as cascas ACIS
    assert info["dropped"] == perdidas
    assert len(doc.modelspace()) == info["entities"] - sum(perdidas.values())
    assert len(doc.modelspace()) == info["kept"] > 0

    # 4. a prévia mostra o que foi entregue
    assert preview is not None and preview[:8] == b"\x89PNG\r\n\x1a\n"


@pytest.mark.skipif(app.find_dwg2dxf() is None, reason="dwg2dxf ausente em bin/")
def test_dxf_renomeado_nao_passa_pelo_libredwg(tmp_path):
    import ezdxf
    doc = ezdxf.new("R2010")
    doc.modelspace().add_line((0, 0), (100, 50))
    fake = tmp_path / "renomeado.dwg"
    doc.saveas(fake)

    dxf_bytes, preview, info = app.convert_dwg_to_dxf(str(fake))
    assert info["dwgversion"] == "DXF renomeado"
    assert info["entities"] == 1
    assert info["repairs"] == 0
    saida = reler(dxf_bytes, tmp_path)
    assert len(saida.modelspace()) == 1
    assert saida.dxfversion == "AC1024"


def test_arquivo_que_nao_e_dwg(tmp_path):
    fake = tmp_path / "foto.dwg"
    fake.write_bytes(b"\x89PNG\r\n\x1a\n" + zlib.compress(b"x" * 100))
    with pytest.raises(app.ConversionError):
        app.convert_dwg_to_dxf(str(fake))


def test_pdf_renomeado_para_dwg(tmp_path):
    fake = tmp_path / "manual.dwg"
    fake.write_bytes(b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n" + b"0" * 200)
    with pytest.raises(app.ConversionError):
        app.convert_dwg_to_dxf(str(fake))


@pytest.mark.skipif(app.find_dwg2dxf() is None, reason="dwg2dxf ausente em bin/")
def test_dwg_corrompido(tmp_path):
    data = bytearray((FIXTURES / "sample_2018.dwg").read_bytes())
    data[64:] = b"\x00" * (len(data) - 64)
    fake = tmp_path / "corrompido.dwg"
    fake.write_bytes(bytes(data))
    with pytest.raises(app.ConversionError):
        app.convert_dwg_to_dxf(str(fake))


def test_mime_de_saida():
    """image/vnd.dxf é o tipo registrado na IANA (registro "image"); o
    costumeiro "application/dxf" não existe em registro nenhum."""
    assert app.TARGET_MIME == "image/vnd.dxf"
