"""O texto do DXF entregue tem de APARECER em quem abre o arquivo.

O dono converteu a prancha da torre, abriu o DXF e não viu texto nenhum. O
arquivo não estava errado: tinha os 33 MTEXT do desenho original. O problema é
que MTEXT é a entidade que metade dos programas que leem DXF simplesmente não
desenha — abre o arquivo, mostra o desenho e omite o texto, sem aviso.

Medido no LibreOffice Draw com a prancha real:
  mesma prancha com MTEXT -> 0 caractere de texto
  mesma prancha com TEXT  -> o texto todo

Estes testes exigem que o arquivo entregue não contenha MTEXT.
"""
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import app  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"
PRIVATE = FIXTURES / "private"


def reler(dxf_bytes: bytes, tmp_path: Path):
    import ezdxf
    p = tmp_path / "entregue.dxf"
    p.write_bytes(dxf_bytes)
    return ezdxf.readfile(p)


def desenho_com_mtext(tmp_path: Path) -> Path:
    """DWG não dá para fabricar aqui; um DXF renomeado para .dwg segue o mesmo
    caminho do app (o app trata esse caso sem passar pelo LibreDWG)."""
    import ezdxf
    doc = ezdxf.new("R2004", setup=True)
    msp = doc.modelspace()
    msp.add_line((0, 0), (100, 0))
    m = msp.add_mtext("PRIMEIRA LINHA\nSEGUNDA LINHA")
    m.set_location((10, 10))
    m.dxf.char_height = 2.5
    caminho = tmp_path / "com_mtext.dwg"
    doc.saveas(caminho)
    return caminho


def test_o_arquivo_entregue_nao_leva_mtext(tmp_path):
    caminho = desenho_com_mtext(tmp_path)
    dxf_bytes, _preview, info = app.convert_dwg_to_dxf(str(caminho))

    assert info["exploded_mtext"] == 1, info
    doc = reler(dxf_bytes, tmp_path)
    tipos = {e.dxftype() for e in doc.modelspace()}
    assert "MTEXT" not in tipos, "o MTEXT foi entregue e some em leitores simples"
    assert "TEXT" in tipos, tipos


def test_as_duas_linhas_do_paragrafo_continuam_no_arquivo(tmp_path):
    """Converter não pode custar texto: as duas linhas do parágrafo têm de
    estar no arquivo entregue, cada uma no seu TEXT."""
    caminho = desenho_com_mtext(tmp_path)
    dxf_bytes, _preview, _info = app.convert_dwg_to_dxf(str(caminho))
    doc = reler(dxf_bytes, tmp_path)
    escrito = " ".join(e.dxf.text for e in doc.modelspace().query("TEXT"))
    assert "PRIMEIRA" in escrito and "SEGUNDA" in escrito, escrito


def test_desenho_sem_mtext_fica_intocado(tmp_path):
    """Quem não tem MTEXT não paga nada: nenhuma conversão, nenhum aviso."""
    import ezdxf
    doc = ezdxf.new("R2004", setup=True)
    doc.modelspace().add_line((0, 0), (10, 10))
    caminho = tmp_path / "sem_texto.dwg"
    doc.saveas(caminho)

    _dxf, _preview, info = app.convert_dwg_to_dxf(str(caminho))
    assert info["exploded_mtext"] == 0


# --- a prova de verdade: abrir no LibreOffice, que é o leitor do dono -------

def _achar_soffice():
    """O LibreOffice não entra no PATH no Windows; procura também onde o
    instalador o coloca. Este app não usa LibreOffice para converter — ele
    entra aqui só como o LEITOR de DXF com que o dono abriu o arquivo."""
    achado = shutil.which("soffice") or shutil.which("libreoffice")
    if achado:
        return achado
    for p in (r"C:\Program Files\LibreOffice\program\soffice.exe",
              r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
              "/Applications/LibreOffice.app/Contents/MacOS/soffice"):
        if Path(p).is_file():
            return p
    return None


SOFFICE = _achar_soffice()


def texto_visto_pelo_libreoffice(dxf: Path, work: Path) -> str:
    """Abre o DXF no LibreOffice e devolve o texto que ele desenhou. É o
    mesmo motor de importação de DXF que o dono usa na máquina dele."""
    import pymupdf

    perfil = work / f"perfil_{uuid.uuid4().hex}"
    subprocess.run(
        [SOFFICE, "--headless", "--norestore", "--nolockcheck", "--nodefault",
         f"-env:UserInstallation={perfil.as_uri()}",
         "--convert-to", "pdf", "--outdir", str(work), str(dxf)],
        capture_output=True, text=True, errors="replace", timeout=300,
    )
    pdf = work / (dxf.stem + ".pdf")
    if not pdf.exists():
        return ""
    with pymupdf.open(str(pdf)) as d:
        return "\n".join(p.get_text("text") for p in d)


@pytest.mark.skipif(SOFFICE is None, reason="LibreOffice ausente nesta máquina")
def test_o_leitor_do_dono_enxerga_o_texto(tmp_path):
    caminho = desenho_com_mtext(tmp_path)
    dxf_bytes, _preview, _info = app.convert_dwg_to_dxf(str(caminho))
    entregue = tmp_path / "entregue.dxf"
    entregue.write_bytes(dxf_bytes)

    visto = texto_visto_pelo_libreoffice(entregue, tmp_path)
    assert "PRIMEIRA" in visto.upper(), f"o leitor não desenhou o texto: {visto!r}"
    assert "SEGUNDA" in visto.upper(), f"o leitor não desenhou o texto: {visto!r}"


@pytest.mark.skipif(SOFFICE is None, reason="LibreOffice ausente nesta máquina")
def test_o_mtext_cru_realmente_some_no_leitor(tmp_path):
    """Prova que o teste acima discrimina: o MESMO desenho, entregue como o
    app fazia antes (com MTEXT), não mostra nada no leitor."""
    import ezdxf
    doc = ezdxf.new("R2004", setup=True)
    msp = doc.modelspace()
    msp.add_line((0, 0), (100, 0))
    m = msp.add_mtext("PRIMEIRA LINHA\nSEGUNDA LINHA")
    m.set_location((10, 10))
    m.dxf.char_height = 2.5
    cru = tmp_path / "cru_com_mtext.dxf"
    doc.saveas(cru)

    visto = texto_visto_pelo_libreoffice(cru, tmp_path)
    assert "PRIMEIRA" not in visto.upper(), (
        "este leitor passou a desenhar MTEXT; a conversão pode ter deixado de "
        f"ser necessária. Texto visto: {visto!r}"
    )


@pytest.mark.skipif(
    SOFFICE is None or not (PRIVATE / "torre.dwg").exists(),
    reason="LibreOffice ou a prancha real do dono ausente",
)
def test_prancha_real_do_dono_abre_com_texto(tmp_path):
    """A prancha que motivou a queixa: 717 entidades, 33 MTEXT. Depois da
    conversão o leitor tem de mostrar as palavras do desenho."""
    dxf_bytes, _preview, info = app.convert_dwg_to_dxf(str(PRIVATE / "torre.dwg"))
    assert info["exploded_mtext"] == 33, info

    entregue = tmp_path / "torre.dxf"
    entregue.write_bytes(dxf_bytes)
    visto = texto_visto_pelo_libreoffice(entregue, tmp_path).upper()
    for palavra in ("TORRE", "MÓDULO", "PARAFUSOS", "30.00"):
        assert palavra in visto, f"{palavra!r} não apareceu no leitor"
