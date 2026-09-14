"""A prévia precisa ter resolução para o texto de uma prancha de CAD.

O dono reclamou que a torre "saiu sem os textos". O DXF entregue tinha os 33
MTEXT intactos — o que faltava era resolução e largura na PRÉVIA: numa
prancha de 30 unidades com cotas de 0,12, a 1600 px a menor cota fica com
5,7 px na imagem e, reduzida para a coluna de 416 px do app, com 1,6 px —
some. Este teste mede a altura da menor letra na imagem gerada e reprova na
resolução antiga.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import app  # noqa: E402

# Piso de legibilidade: abaixo disto a letra não tem traço e volume suficientes
# para ser lida nem ampliando a imagem. 1600 px davam 5,7 px e reprovam aqui.
ALTURA_MINIMA_PX = 12.0

# Prancha sintética com as proporções medidas no desenho real do dono:
# 30 unidades de largura, texto de 0,12 unidade (a menor cota da torre).
LARGURA_DESENHO = 30.0
ALTURA_TEXTO = 0.12


def prancha_com_texto_pequeno(tmp_path: Path) -> Path:
    import ezdxf
    doc = ezdxf.new("R2004", setup=True)
    msp = doc.modelspace()
    # moldura que fixa a extensão do desenho
    msp.add_lwpolyline(
        [(0, 0), (LARGURA_DESENHO, 0), (LARGURA_DESENHO, LARGURA_DESENHO), (0, LARGURA_DESENHO)],
        close=True,
    )
    texto = msp.add_text("2.00", height=ALTURA_TEXTO)
    texto.dxf.insert = (LARGURA_DESENHO / 2, LARGURA_DESENHO / 2)
    caminho = tmp_path / "prancha.dxf"
    doc.saveas(caminho)
    return caminho


def test_a_menor_letra_sobrevive_na_previa(tmp_path):
    import ezdxf
    import pymupdf

    caminho = prancha_com_texto_pequeno(tmp_path)
    app.prepare_font_environment()
    doc = ezdxf.readfile(caminho)
    png = app.render_preview(doc)
    assert png, "a prévia não foi gerada"

    pix = pymupdf.Pixmap(png)
    lado_maior = max(pix.width, pix.height)
    altura_na_imagem = ALTURA_TEXTO / LARGURA_DESENHO * lado_maior
    assert altura_na_imagem >= ALTURA_MINIMA_PX, (
        f"a menor letra sai com {altura_na_imagem:.1f} px na prévia de "
        f"{pix.width}x{pix.height}; abaixo de {ALTURA_MINIMA_PX} px o texto "
        "desaparece quando a imagem é reduzida para a largura da coluna"
    )


def test_o_texto_realmente_vira_tinta_na_previa(tmp_path):
    """Resolução não basta: o texto tem de ser DESENHADO. Mede tinta na faixa
    onde o texto está, e só ali — se a fonte não resolvesse, a faixa do meio
    sairia branca e o resto da moldura continuaria preto."""
    import ezdxf
    import pymupdf

    caminho = prancha_com_texto_pequeno(tmp_path)
    app.prepare_font_environment()
    doc = ezdxf.readfile(caminho)
    pix = pymupdf.Pixmap(app.render_preview(doc))

    # faixa horizontal no meio da imagem, longe da moldura das bordas
    y0, y1 = int(pix.height * 0.45), int(pix.height * 0.55)
    x0, x1 = int(pix.width * 0.15), int(pix.width * 0.85)
    escuros = sum(
        1
        for y in range(y0, y1)
        for x in range(x0, x1, 2)
        if sum(pix.pixel(x, y)[:3]) < 400
    )
    assert escuros > 50, f"nenhum texto desenhado no meio da prévia ({escuros} pixels escuros)"


@pytest.mark.skipif(
    not (Path(__file__).parent / "fixtures" / "private" / "torre.dwg").exists(),
    reason="prancha real do dono ausente (fica fora do git)",
)
def test_prancha_real_do_dono_tem_texto_legivel():
    """Desenho real que motivou a queixa: 717 entidades, 33 MTEXT, cotas de
    0,12 unidade. Conta as faixas de tinta do carimbo, no canto inferior
    direito — onde ficam o título e o nome do proprietário."""
    import pymupdf

    privado = Path(__file__).parent / "fixtures" / "private" / "torre.dwg"
    dxf_bytes, preview, info = app.convert_dwg_to_dxf(str(privado))
    assert info["entities"] == 717
    assert preview, "a prancha real não gerou prévia"

    pix = pymupdf.Pixmap(preview)
    assert max(pix.width, pix.height) >= 3500, (pix.width, pix.height)

    # carimbo: 66%-100% da largura, 62%-98% da altura
    x0, x1 = int(pix.width * 0.66), pix.width - 1
    y0, y1 = int(pix.height * 0.62), int(pix.height * 0.98)
    linhas_com_tinta = sum(
        1
        for y in range(y0, y1, 3)
        if any(sum(pix.pixel(x, y)[:3]) < 400 for x in range(x0, x1, 3))
    )
    # o carimbo tem título, endereço, proprietário, data e número da prancha:
    # dezenas de linhas com tinta, não meia dúzia
    assert linhas_com_tinta > 40, f"carimbo quase vazio: {linhas_com_tinta} linhas com tinta"
