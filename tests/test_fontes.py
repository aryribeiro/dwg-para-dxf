"""Fontes: aqui elas não entram no arquivo entregue — entram na PRÉVIA.

O DXF guarda o NOME da fonte, não os desenhos das letras. Quem abrir o
arquivo vê a fonte da própria máquina. Mas a prévia na tela é o que o
usuário usa para conferir se o desenho veio inteiro, e com a fonte errada
o texto quebra onde o AutoCAD não quebra e as linhas se atropelam.

A ORDEM é o que já falhou uma vez (v1.1.2 do app irmão de PNG): ler o DXF
já mede texto, e essa primeira medição fixa a fonte. Registrar as fontes
depois da leitura não adianta nada.
"""
import inspect
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import app  # noqa: E402


def test_arial_vem_no_repositorio():
    """A coleção de fontes tem de trazer a Arial: é ela que a maioria dos
    desenhos pede e que não existe no servidor."""
    assert (ROOT / "static" / "fonts" / "arial.ttf").is_file()


def test_ezdxf_resolve_arial_para_o_arquivo_do_repositorio():
    from ezdxf.fonts import fonts

    app.prepare_font_environment()
    for pedido in ("Arial", "ARIAL.TTF", "arial.ttf"):
        face = (fonts.get_font_face(pedido) if pedido.lower().endswith(".ttf")
                else fonts.resolve_font_face(pedido))
        assert face.filename.lower() == "arial.ttf", (pedido, face)


def test_fontes_sao_registradas_antes_de_ler_o_desenho():
    """Guarda de ordem: prepare_font_environment() tem de aparecer no corpo
    de sanitize_dxf ANTES de read_dxf_with_repair. Foi exatamente essa
    inversão que fez o texto embolar em produção no app irmão, num defeito
    que só existe em servidor com fontes de sistema mas sem a Arial — ou
    seja, invisível para os outros testes desta suíte."""
    linhas = inspect.getsource(app.sanitize_dxf).splitlines()
    prepara = next(i for i, l in enumerate(linhas) if "prepare_font_environment()" in l)
    le = next(i for i, l in enumerate(linhas) if "read_dxf_with_repair(" in l)
    assert prepara < le, "prepare_font_environment() precisa vir antes da leitura"


def test_pasta_de_fontes_do_repositorio_esta_registrada():
    """Prova de ambiente: o catálogo do ezdxf enxerga a pasta do repo."""
    app.prepare_font_environment()
    quantas = sum(1 for _ in (ROOT / "static" / "fonts").glob("*.ttf"))
    assert quantas >= 150, f"só {quantas} fontes em static/fonts"
