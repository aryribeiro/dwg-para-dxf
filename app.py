import streamlit as st
import subprocess
import io
import re
import stat
import tempfile
import shutil
import uuid
from pathlib import Path
import platform
import threading
import time
import random

import ezdxf
from ezdxf import recover, bbox
from ezdxf.lldxf.const import DXFStructureError, acad_release
from ezdxf.addons.drawing import Frontend, RenderContext, config, layout
from ezdxf.addons.drawing.pymupdf import PyMuPdfBackend

# ---------------------------------------------------------------------------
# CONFIGURAÇÃO DE PÁGINA E CSS (compacto, para caber no lightbox do AtlasDocs)
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Conversor DWG para DXF",
    page_icon="📐",
    layout="centered",
    initial_sidebar_state="collapsed",
)

st.markdown("""
<style>
    .main {
        background-color: #ffffff;
        color: #333333;
    }
    .block-container {
        padding-top: 0rem !important;
        padding-bottom: 0rem !important;
        /* Uma prancha de CAD não cabe numa coluna estreita: espremida em
           28rem (416 px na tela), a cota de 0,12 unidade de um desenho de
           30 unidades vira 1,6 px e some — o desenho parece vir "sem texto".
           64rem é um TETO, não uma largura fixa: dentro de um lightbox
           estreito o contêiner encolhe sozinho para o espaço disponível. */
        max-width: 64rem !important;
    }
    header {display: none !important;}
    footer {display: none !important;}
    #MainMenu {display: none !important;}
    div[data-testid="stAppViewBlockContainer"] {
        padding-top: 0 !important;
        padding-bottom: 0 !important;
    }
    div[data-testid="stVerticalBlock"] {
        gap: 0 !important;
        padding-top: 0 !important;
        padding-bottom: 0 !important;
    }
    .element-container {
        margin-top: 0 !important;
        margin-bottom: 0 !important;
    }
    .stDownloadButton button {
        width: 100% !important;
        padding: 0.6rem 2rem;
    }
</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# CONVERSÃO: DWG (AutoCAD) -> DXF
# Escopo único e fixo — este app não lida com nenhum outro par de formatos.
# Cadeia: dwg2dxf (GNU LibreDWG, binário em bin/) -> ezdxf (leitura com
# reparo) -> ezdxf grava o DXF de volta -> esse arquivo é o entregue.
#
# POR QUE NÃO ENTREGAR O DXF CRU DO LibreDWG:
# em DWG com bits corrompidos o dwg2dxf grava lixo com quebra de linha dentro
# de um valor de texto e, dali em diante, código e valor trocam de lugar. Esse
# arquivo o AutoCAD também não abre. O que o ezdxf conseguiu ler é o desenho
# de verdade; regravá-lo devolve um DXF bem formado, com a MESMA versão de DXF
# da origem (doc.dxfversion não é alterado em nenhum ponto do caminho).
# ---------------------------------------------------------------------------
SOURCE_EXT = ".dwg"
TARGET_EXT = "dxf"
# image/vnd.dxf é o tipo REGISTRADO na IANA para DXF (registro "image",
# entrada vnd.dxf). "application/dxf", usado por costume, não existe em
# nenhum dos dois registros. Conferido em iana.org/assignments/media-types.
TARGET_MIME = "image/vnd.dxf"

# A prévia serve para conferir que o desenho veio inteiro — o que se baixa é
# o DXF. Medido numa prancha real de 30 unidades com cotas de 0,12: a 1600 px
# a menor cota fica com 5,7 px na imagem, legível só em 1:1; ampliar a imagem
# na tela cheia do Streamlit já não tinha resolução para dar. A 4000 px a
# mesma cota fica com 15,5 px e a tela cheia vira uma leitura de verdade.
# É o mesmo número do app irmão dwg-para-png, já aprovado em produção.
PREVIEW_LONG_SIDE_PX = 4000
PREVIEW_LONG_SIDE_IN = 10.0
PREVIEW_MIN_SIDE_PX = 200
PAGE_MARGIN_MM = 5.0
DWG2DXF_TIMEOUT = 120      # segundos por tentativa

BIN_DIR = Path(__file__).resolve().parent / "bin"

# Código gravado nos 6 primeiros bytes do DWG -> nome da versão do AutoCAD.
DWG_VERSIONS = {
    "AC1.2": "R1.2", "AC1.40": "R1.4", "AC1.50": "R2.05", "AC2.10": "R2.1",
    "AC2.21": "R2.21", "AC2.22": "R2.22", "AC1001": "R2.4", "AC1002": "R2.5",
    "AC1003": "R2.6", "AC1004": "R9", "AC1006": "R10", "AC1009": "R11/R12",
    "AC1012": "R13", "AC1014": "R14", "AC1015": "2000", "AC1018": "2004",
    "AC1021": "2007", "AC1024": "2010", "AC1027": "2013", "AC1032": "2018",
}


class ConversionError(RuntimeError):
    """Falha de conversão — o erro já foi exibido na interface."""


# ---------------------------------------------------------------------------
# LOCALIZAÇÃO DO BINÁRIO dwg2dxf (GNU LibreDWG)
# ---------------------------------------------------------------------------
def find_dwg2dxf():
    """Procura o dwg2dxf em bin/ (Linux estático no repo; .exe local no
    Windows, fora do git) e por último no PATH. Garante o bit de execução,
    porque um clone pode chegar sem ele."""
    if platform.system() == "Windows":
        candidates = [BIN_DIR / "dwg2dxf.exe"]
    else:
        candidates = [BIN_DIR / "dwg2dxf"]
    for c in candidates:
        if c.is_file():
            if platform.system() != "Windows":
                try:
                    mode = c.stat().st_mode
                    if not mode & stat.S_IXUSR:
                        c.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
                except OSError:
                    pass
            return str(c)
    found = shutil.which("dwg2dxf")
    return found


# ---------------------------------------------------------------------------
# INSPEÇÃO DO CABEÇALHO: versão do DWG e impostores (DXF/PDF/ZIP renomeados)
# ---------------------------------------------------------------------------
def inspect_header(data: bytes):
    """Devolve (tipo, versão). tipo: 'dwg', 'dxf' ou 'outro'.
    Um .dwg de verdade começa com o código da versão (ex.: AC1032).
    Um DXF renomeado para .dwg é comum e não passa pelo dwg2dxf."""
    head = data[:64]
    code = head[:6].decode("ascii", errors="replace")
    if code[:2] == "AC" and (code[2:6].isdigit() or code[2] == "1" and "." in code or code[2] == "2" and "." in code):
        return "dwg", DWG_VERSIONS.get(code.rstrip("\x00"), code)
    if head.startswith(b"AutoCAD Binary DXF"):
        return "dxf", "binário"
    text = data[:512].decode("ascii", errors="ignore")
    if re.match(r"\s*0\s*[\r\n]+\s*SECTION", text) or "999" in text[:8] and "SECTION" in text:
        return "dxf", "ASCII"
    return "outro", ""


# ---------------------------------------------------------------------------
# RESILIÊNCIA: LIMITE DE PROCESSOS CONCORRENTES E LIMPEZA DE ÓRFÃOS
# ---------------------------------------------------------------------------
@st.cache_resource(show_spinner=False)
def get_conversion_slots():
    """Semáforo global do processo: no máximo 2 conversões simultâneas.
    Um DWG grande leva o dwg2dxf a centenas de MB e o desenho ainda fica
    inteiro na memória do ezdxf enquanto é regravado; sem este limite,
    N usuários = N vezes isso e o container do Streamlit Cloud (1 GB)
    morre por falta de memória."""
    return threading.BoundedSemaphore(2)


@st.cache_resource(show_spinner=False)
def cleanup_stale_artifacts():
    """Remove pastas dwg_* órfãs (de execuções que morreram no meio) com
    mais de 1h, evitando encher o disco do container. Roda 1x por boot."""
    cutoff = time.time() - 3600
    tmp = Path(tempfile.gettempdir())
    for path in tmp.glob("dwg_*"):
        try:
            if path.stat().st_mtime < cutoff:
                if path.is_dir():
                    shutil.rmtree(path, ignore_errors=True)
                else:
                    path.unlink()
        except OSError:
            pass
    return True


# ---------------------------------------------------------------------------
# FONTES: o container do Streamlit Cloud pode não ter nenhuma fonte, e sem
# fonte o ezdxf recusa desenhar texto ("no fonts available"). O repo carrega
# a coleção em static/fonts como reserva; o packages.txt pede as fontes do
# sistema por cima disso.
# ---------------------------------------------------------------------------
STATIC_FONTS_DIR = Path(__file__).resolve().parent / "static" / "fonts"


@st.cache_resource(show_spinner=False)
def prepare_font_environment():
    """Reconstrói o catálogo de fontes do ezdxf: pastas do sistema + a pasta
    do repo. Roda 1x por boot, antes da primeira leitura de desenho, porque o
    ezdxf fixa a fonte de reserva na primeira consulta."""
    from ezdxf.fonts import fonts as ezfonts
    fm = ezfonts.font_manager
    fm.clear()
    fm.build()
    if STATIC_FONTS_DIR.is_dir():
        fm.build([str(STATIC_FONTS_DIR)], support_dirs=False)
    fm.add_synonyms(ezfonts.FONT_SYNONYMS, reverse=True)
    return fm.fallback_font_name()


# ---------------------------------------------------------------------------
# ETAPA 1: DWG -> DXF COM O dwg2dxf (subprocesso com timeout e backoff)
# ---------------------------------------------------------------------------
def run_subprocess_with_backoff(cmd_args, max_retries=2, base_delay=0.5, max_delay=3.0):
    """Repete só em timeout ou erro do sistema; um DWG que o LibreDWG não
    lê falha igual na segunda vez, então não vale insistir por conteúdo."""
    last = None
    for attempt in range(max_retries):
        try:
            last = subprocess.run(
                cmd_args,
                capture_output=True,
                text=True,
                errors="replace",
                timeout=DWG2DXF_TIMEOUT,
            )
            return last
        except (subprocess.TimeoutExpired, OSError):
            last = None
        if attempt < max_retries - 1:
            calculated_delay = min(max_delay, base_delay * (2 ** attempt))
            jitter = random.uniform(0, 0.3)
            time.sleep(calculated_delay + jitter)
    return last


_WARN_UNKNOWN = re.compile(r"Unknown object", re.I)
# "Skip CELLSTYLEMAP" (objeto inteiro pulado) conta; "Skip HATCH common
# handles due to..." (só os handles) não — a hachura é desenhada normalmente.
_WARN_CLASS = re.compile(r"(?:Unhandled Object\s+([A-Z][A-Z0-9_]+)|Skip\s+([A-Z][A-Z0-9_]+)\s*$)", re.M)
# Classes que o LibreDWG deixa de escrever mas que nunca aparecem no desenho
# (estilos, materiais, dicionários, ajustes de plotagem). Avisar sobre elas
# em todo arquivo transformaria o aviso em ruído que ninguém lê.
_NON_GRAPHICAL = re.compile(
    r"(STYLE|STYLEMAP|MATERIAL|DICTIONARY|XRECORD|PLOTSETTINGS|LAYOUT|"
    r"SORTENTSTABLE|VISUALSTYLE|SCALE|DIMASSOC|CONTEXTDATA\w*)$"
)


def summarize_libredwg_warnings(stderr: str):
    """O dwg2dxf imprime SUCCESS mesmo perdendo objetos. Aqui o stderr vira
    números e nomes que a interface mostra, em vez de um sucesso mudo.
    "Unstable Class" não conta: o objeto foi lido, só o decodificador é
    marcado como instável."""
    unknown = len(_WARN_UNKNOWN.findall(stderr or ""))
    found = {a or b for a, b in _WARN_CLASS.findall(stderr or "")}
    classes = sorted(c for c in found if not _NON_GRAPHICAL.search(c))
    return unknown, classes


def dwg_to_dxf(dwg_path: Path, work_dir: Path):
    """Converte com o dwg2dxf. Devolve (caminho_do_dxf, avisos) ou levanta
    ConversionError com a mensagem já exibida."""
    exe = find_dwg2dxf()
    if not exe:
        st.error("❌ O conversor de DWG (LibreDWG) não foi encontrado neste servidor.")
        raise ConversionError("dwg2dxf ausente")

    dxf_path = work_dir / (dwg_path.stem + "_bruto.dxf")
    cmd_args = [exe, "-y", "-o", str(dxf_path), str(dwg_path)]
    result = run_subprocess_with_backoff(cmd_args)

    produced = dxf_path.exists() and dxf_path.stat().st_size > 0
    if result is None and not produced:
        st.error("❌ O desenho demorou demais para ser lido. Tente um arquivo menor.")
        raise ConversionError("timeout")
    if not produced:
        stderr = (result.stderr or "").strip() if result else ""
        tail = stderr.splitlines()[-1] if stderr else "sem detalhes"
        st.error(f"❌ Não foi possível ler este DWG. ({tail})")
        raise ConversionError("dwg2dxf falhou")

    stderr = result.stderr if result else ""
    return dxf_path, summarize_libredwg_warnings(stderr)


# ---------------------------------------------------------------------------
# ETAPA 2: LER O DXF COM REPARO E REGRAVAR — O ARQUIVO ENTREGUE
# ---------------------------------------------------------------------------
_DXF_ERROR_LINE = re.compile(r"at line (\d+)")
MAX_DXF_REPAIRS = 200


def read_dxf_with_repair(dxf_path: Path):
    """Lê o DXF em modo de recuperação e conserta o defeito típico do
    LibreDWG: em DWG com bits corrompidos ele grava lixo com quebra de
    linha dentro de um valor de texto, e a partir dali código e valor
    trocam de lugar ("Invalid group code '</Material>' at line N").
    Apagar a linha apontada realinha o fluxo; repete até ler ou esgotar.
    Devolve (doc, número_de_reparos)."""
    lines = dxf_path.read_bytes().split(b"\n")
    for repairs in range(MAX_DXF_REPAIRS + 1):
        try:
            doc, _auditor = recover.read(io.BytesIO(b"\n".join(lines)))
            return doc, repairs
        except DXFStructureError as e:
            m = _DXF_ERROR_LINE.search(str(e))
            if not m:
                raise
            n = int(m.group(1))
            if n < 1 or n > len(lines):
                raise
            del lines[n - 1]
    raise DXFStructureError("limite de reparos atingido")


def _count_types(msp):
    contagem = {}
    for e in msp:
        t = e.dxftype()
        contagem[t] = contagem.get(t, 0) + 1
    return contagem


def sanitize_dxf(dxf_path: Path, work_dir: Path, stem: str):
    """Lê o DXF (com reparo) e o grava de volta com o ezdxf. O arquivo
    gravado é o que o usuário baixa. Devolve (caminho, doc_relido, info).

    A releitura com ezdxf.readfile — o leitor ESTRITO, não o de recuperação —
    é a prova de que o arquivo entregue abre: se passar aqui, passa em
    qualquer leitor de DXF que siga a especificação."""
    # As fontes têm de ser registradas ANTES de abrir o desenho. Ler o DXF já
    # mede texto (o cálculo dos limites do desenho passa pelos MTEXT), e essa
    # primeira medição fixa a fonte. Se a Arial ainda não estiver registrada,
    # o desenho inteiro é medido com a fonte do sistema, mais larga. Só
    # aparece em servidor que TEM fontes de sistema — por isso passava na
    # bancada. Foi o defeito da v1.1.1 do app irmão de PNG.
    prepare_font_environment()
    try:
        doc, repairs = read_dxf_with_repair(dxf_path)
    except Exception:
        st.error("❌ O desenho foi lido, mas a estrutura veio corrompida e não deu para reescrever.")
        raise ConversionError("dxf inválido")

    msp = doc.modelspace()
    antes = _count_types(msp)
    info = {
        "dxfversion": doc.dxfversion,
        "entities": len(msp),
        "layers": len(doc.layers),
        "repairs": repairs,
    }
    info.update(fonts_report(doc, msp))

    out_path = work_dir / (stem + ".dxf")
    try:
        # saveas grava na versão de DXF do próprio documento (doc.dxfversion),
        # que veio do DWG de origem e não é tocada em nenhum ponto do caminho.
        doc.saveas(out_path)
    except Exception:
        st.error("❌ O desenho foi lido, mas não deu para gravar o DXF de saída.")
        raise ConversionError("falha ao gravar")

    try:
        final = ezdxf.readfile(out_path)
    except Exception:
        st.error("❌ O DXF gerado não passou na conferência de leitura e não vai ser entregue.")
        raise ConversionError("dxf de saída ilegível")

    # O que entrou e não saiu, contado no arquivo entregue em vez de
    # previsto. Na prática são as entidades ACIS (3DSOLID, REGION, BODY,
    # superfícies): a forma delas não é geometria DXF, é um bloco de dados
    # do modelador que, em DXF R2013+, mora na seção ACDSDATA — seção que o
    # LibreDWG não escreve. Elas chegam ocas e o ezdxf se recusa a regravar
    # uma casca sem geometria. Medido em tests/fixtures/example_2018.dwg.
    depois = _count_types(final.modelspace())
    info["dropped"] = {t: antes[t] - depois.get(t, 0)
                       for t in antes if antes[t] > depois.get(t, 0)}
    info["kept"] = len(final.modelspace())
    return out_path, final, info


# ---------------------------------------------------------------------------
# ETAPA 3: PRÉVIA NA TELA — RENDERIZA O ARQUIVO ENTREGUE
# ---------------------------------------------------------------------------
def page_for_extents(width: float, height: float):
    """Página virtual com o lado maior fixo em polegadas e a proporção do
    desenho; o DPI é escolhido para que o lado maior tenha o número de
    pixels da prévia."""
    width = max(width, 1e-9)
    height = max(height, 1e-9)
    if width >= height:
        w_in, h_in = PREVIEW_LONG_SIDE_IN, PREVIEW_LONG_SIDE_IN * height / width
    else:
        w_in, h_in = PREVIEW_LONG_SIDE_IN * width / height, PREVIEW_LONG_SIDE_IN
    dpi = int(round(PREVIEW_LONG_SIDE_PX / PREVIEW_LONG_SIDE_IN))
    min_in = PREVIEW_MIN_SIDE_PX / dpi
    w_in = max(w_in, min_in)
    h_in = max(h_in, min_in)
    page = layout.Page(
        w_in * 25.4, h_in * 25.4, layout.Units.mm,
        margins=layout.Margins.all(PAGE_MARGIN_MM),
    )
    return page, dpi


def render_preview(doc):
    """PNG do desenho ENTREGUE, só para conferir na tela que veio inteiro.
    Devolve os bytes ou None quando não há nada desenhável — um DXF de
    linhas infinitas ou de sólidos 3D é um arquivo válido, e recusar a
    conversão por causa da prévia seria trocar o produto pelo enfeite."""
    msp = doc.modelspace()
    extents = bbox.extents(msp, fast=True)
    if not extents.has_data:
        return None
    page, dpi = page_for_extents(extents.size.x, extents.size.y)
    ctx = RenderContext(doc)
    backend = PyMuPdfBackend()
    cfg = config.Configuration(
        background_policy=config.BackgroundPolicy.WHITE,
        color_policy=config.ColorPolicy.COLOR,
    )
    Frontend(ctx, backend, config=cfg).draw_layout(msp, finalize=True)
    if not backend.player().bbox().has_data:
        # há entidades, mas nenhuma desenhável (linhas infinitas, camadas
        # desligadas, sólidos 3D...) — sem isto o backend estoura ValueError
        return None
    return backend.get_pixmap_bytes(
        page, fmt="png", dpi=dpi, settings=layout.Settings(fit_page=True),
    ) or None


# ---------------------------------------------------------------------------
# QUE FONTE FOI USADA DE VERDADE
# Aqui a fonte não vai dentro do arquivo: o DXF guarda o NOME da fonte, e
# quem abrir o desenho usa a fonte da própria máquina. A troca só afeta a
# PRÉVIA na tela. Ainda assim vale dizer qual foi, porque é a prévia que o
# usuário usa para conferir se o desenho veio inteiro.
# ---------------------------------------------------------------------------
_INLINE_FONT = re.compile(r"\\f([^|;}\\]+)")
# Fontes vetoriais clássicas do AutoCAD (.shx): não existem livres, a troca
# por uma TrueType é o esperado e não vale um aviso.
_SHX_CLASSICAS = {
    "txt", "monotxt", "simplex", "complex", "italic", "italicc", "italict",
    "romans", "romand", "romanc", "romant", "scripts", "scriptc", "greeks",
    "greekc", "gothice", "gothicg", "gothici", "syastro", "symap", "symath",
    "symeteo", "symusic", "iso", "isocp", "isocp2", "isocp3", "isoct",
    "isoct2", "isoct3", "amgdt", "bigfont", "whgtxt", "whgtxt2",
}


def fonts_report(doc, msp):
    """Devolve {'fonts': [...], 'font_swaps': [('pedida', 'usada'), ...]}."""
    from ezdxf.fonts import fonts as ezfonts

    pedidas = set()
    for style in doc.styles:
        nome = style.dxf.get("font", "") or ""
        if nome:
            pedidas.add(nome)
    for e in msp.query("MTEXT"):
        pedidas.update(_INLINE_FONT.findall(e.text or ""))

    usadas, trocas = set(), []
    for pedida in sorted(pedidas):
        try:
            if pedida.lower().endswith((".ttf", ".otf", ".ttc", ".shx")):
                face = ezfonts.get_font_face(pedida)
            else:
                face = ezfonts.resolve_font_face(pedida)
        except Exception:
            continue
        usada = face.filename or ""
        if not usada:
            continue
        usadas.add(face.family or usada)
        stem = Path(pedida).stem.lower()
        mesma = stem == Path(usada).stem.lower() or stem == (face.family or "").lower()
        if not mesma and not pedida.lower().endswith(".shx") and stem not in _SHX_CLASSICAS:
            trocas.append((pedida, face.family or usada))
    return {"fonts": sorted(usadas), "font_swaps": trocas,
            "fonts_dir": sum(1 for _ in STATIC_FONTS_DIR.glob("*.ttf")) if STATIC_FONTS_DIR.is_dir() else 0}


# ---------------------------------------------------------------------------
# PIPELINE COMPLETO
# ---------------------------------------------------------------------------
def convert_dwg_to_dxf(input_file: str):
    """Converte um .dwg em DXF. Devolve (dxf_bytes, png_da_prévia, info).
    Pasta de trabalho própria por chamada e apagada no finally, mesmo em
    erro."""
    input_path = Path(input_file)
    work_dir = Path(tempfile.gettempdir()) / f"dwg_{uuid.uuid4().hex}"
    try:
        work_dir.mkdir(parents=True, exist_ok=True)
        data = input_path.read_bytes()
        kind, version = inspect_header(data)

        with get_conversion_slots():
            if kind == "dxf":
                # DXF renomeado para .dwg: não precisa do LibreDWG. Ainda
                # passa pelo saneamento, que é o que este app entrega.
                bruto = work_dir / (input_path.stem + "_bruto.dxf")
                shutil.copy2(input_path, bruto)
                warnings = (0, [])
                version = "DXF renomeado"
            elif kind == "dwg":
                bruto, warnings = dwg_to_dxf(input_path, work_dir)
            else:
                st.error("❌ Este arquivo não é um DWG do AutoCAD.")
                raise ConversionError("não é dwg")

            out_path, final_doc, info = sanitize_dxf(bruto, work_dir, input_path.stem)
            dxf_bytes = out_path.read_bytes()
            preview = render_preview(final_doc)

        info["dwgversion"] = version
        info["dxfrelease"] = acad_release.get(info["dxfversion"], info["dxfversion"])
        info["unknown_objects"], info["skipped_classes"] = warnings
        return dxf_bytes, preview, info
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# CACHE DE CONVERSÃO (TTL 1h)
# ---------------------------------------------------------------------------
@st.cache_data(ttl=3600, max_entries=6, show_spinner=False)
def convert_upload_to_dxf(file_name: str, file_bytes: bytes):
    """Converte com cache por conteúdo: clicar em "Baixar DXF" dispara um
    rerun do script e, sem cache, o mesmo arquivo seria reconvertido do
    zero a cada clique. Falhas levantam exceção de propósito — exceção não
    entra no cache, então erros transientes não ficam "grudados" por 1h."""
    with tempfile.TemporaryDirectory() as temp_dir:
        input_path = Path(temp_dir) / (Path(file_name).name or "desenho.dwg")
        input_path.write_bytes(file_bytes)
        return convert_dwg_to_dxf(str(input_path))


# ---------------------------------------------------------------------------
# INTERFACE PRINCIPAL
# ---------------------------------------------------------------------------
def main():
    cleanup_stale_artifacts()
    uploaded_file = st.file_uploader(
        "Arraste e solte seu arquivo aqui",
        type=["dwg"],
        help="Arquivo DWG (AutoCAD). Máximo: 200MB",
        label_visibility="collapsed",
    )

    if uploaded_file is None:
        return

    if (uploaded_file.size / (1024 * 1024)) > 200:
        st.error("❌ Arquivo muito grande! Máximo: 200MB")
        st.stop()

    ext = Path(uploaded_file.name).suffix.lower()
    if ext != SOURCE_EXT:
        st.error("❌ Formato não suportado.")
        return

    with st.spinner(f"Convertendo para {TARGET_EXT.upper()}..."):
        try:
            dxf_bytes, preview, info = convert_upload_to_dxf(
                uploaded_file.name, uploaded_file.getvalue())
        except ConversionError:
            return

    st.success("✅ Conversão concluída!")
    if preview is not None:
        st.image(preview, use_column_width=True)
    else:
        st.info("ℹ️ O arquivo foi convertido, mas não tem nada que possa ser "
                "mostrado numa imagem (linhas infinitas e sólidos 3D não têm "
                "desenho em duas dimensões).")

    detail = (f"AutoCAD {info['dwgversion']} · DXF {info['dxfrelease']} · "
              f"{info['kept']} elementos · {info['layers']} camadas")
    if info["repairs"]:
        detail += f" · {info['repairs']} reparo(s)"
    if info.get("fonts"):
        detail += " · fonte da prévia: " + ", ".join(info["fonts"])
    st.caption(detail)

    if info.get("dropped"):
        perdidos = ", ".join(f"{n} {t}" for t, n in sorted(info["dropped"].items()))
        st.warning(f"⚠️ Não entraram no arquivo final: {perdidos}. Sólidos e "
                   "superfícies do AutoCAD guardam a forma num bloco de dados "
                   "próprio que o leitor livre de DWG não copia, e o que chega "
                   "aqui é uma casca vazia. O resto do desenho está completo.")
    if info.get("font_swaps"):
        trocas = "; ".join(f"{a} por {b}" for a, b in info["font_swaps"])
        st.info(f"ℹ️ Na imagem acima, este servidor trocou {trocas} — ele não tem "
                "essas fontes instaladas. **Isso não afeta o arquivo DXF**: o "
                "desenho guarda o NOME da fonte, e quem abrir vai ver a fonte "
                "da própria máquina.")
    if info["unknown_objects"] or info["skipped_classes"]:
        parts = []
        if info["unknown_objects"]:
            parts.append(f"{info['unknown_objects']} objeto(s) que o leitor não reconheceu "
                         "(em geral de complementos como AutoCAD Architecture ou Civil 3D)")
        if info["skipped_classes"]:
            parts.append("tipos não copiados: " + ", ".join(info["skipped_classes"]))
        st.warning("⚠️ Leitura parcial: " + "; ".join(parts) + ". Confira se falta algo no desenho.")

    st.download_button(
        label=f"📥 Baixar {TARGET_EXT.upper()}",
        data=dxf_bytes,
        file_name=Path(uploaded_file.name).stem + "." + TARGET_EXT,
        mime=TARGET_MIME,
        type="primary",
        use_container_width=True,
    )


if __name__ == "__main__":
    main()
