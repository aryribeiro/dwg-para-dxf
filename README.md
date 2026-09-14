# 📐 Conversor de DWG para DXF

Aplicação web em Python/[Streamlit](https://streamlit.io) que converte desenhos **DWG (AutoCAD) para DXF**, sem AutoCAD.

## 🎯 O que faz

| Entrada | Saída |
| --- | --- |
| `.dwg` (AutoCAD, R13 a 2018) | **`.dxf`** (mesma versão de DXF do desenho de origem) |

Escopo único e fixo — este app não lida com nenhum outro formato de entrada ou saída.

- Interface de tela única (upload → converter → prévia → baixar)
- Mostra uma **imagem do arquivo entregue**, para você conferir que o desenho veio inteiro
- Informa a versão do AutoCAD de origem, a versão do DXF gerado, quantos elementos e camadas ele tem e **avisa quando alguma coisa ficou para trás**
- Processamento em diretórios temporários — nenhum arquivo é armazenado

## ⚙️ Como converte

1. **GNU LibreDWG** ([`bin/dwg2dxf`](https://github.com/LibreDWG/libredwg), binário Linux estático, versão 0.14) lê o DWG e grava um DXF bruto.
2. **[ezdxf](https://ezdxf.mozman.at/)** lê esse DXF em modo de recuperação, consertando o desalinhamento típico do LibreDWG.
3. Cada bloco de **texto de várias linhas** (a entidade `MTEXT` do AutoCAD) vira **texto de uma linha** (`TEXT`), com as quebras de linha, o alinhamento e a rotação recalculados pelo ezdxf. Sem isso o desenho abre **sem texto nenhum** em boa parte dos programas: o LibreOffice Draw, por exemplo, desenha `TEXT` e ignora `MTEXT` calado. Medido numa prancha real: o mesmo desenho entregue com `MTEXT` mostra zero caractere; com `TEXT`, mostra o texto todo.
4. O mesmo ezdxf **grava o desenho de volta em DXF** — e é esse arquivo que você baixa.
5. O arquivo gravado é **reaberto com o leitor estrito** antes de ser entregue, e é dele que sai a imagem da prévia.

### Por que o app não entrega o DXF que o LibreDWG produziu

Porque esse arquivo às vezes não abre. Em DWG com bits corrompidos, o LibreDWG grava lixo com uma quebra de linha no meio de um texto; a partir dali o arquivo inteiro sai do lugar e nem o AutoCAD consegue ler. O que o ezdxf conseguiu ler é o desenho de verdade, e regravá-lo devolve um arquivo bem formado. A versão do DXF de origem é preservada: um desenho do AutoCAD 2018 sai como DXF 2018, um do AutoCAD 2000 sai como DXF 2000.

A prova disso está nos testes: um arquivo propositalmente quebrado entra, o leitor estrito o recusa, e o arquivo que sai do app abre normalmente com as três figuras no lugar.

### O tipo de arquivo declarado no download

O app declara `image/vnd.dxf`, que é o tipo **registrado na IANA** para DXF (lista oficial em [iana.org/assignments/media-types](https://www.iana.org/assignments/media-types/media-types.xhtml), registro `image`, entrada `vnd.dxf`). O `application/dxf` que muita gente usa não consta de nenhum registro oficial — conferido nas duas listas, a de `image` e a de `application`.

## 📏 Limites honestos

- **Sólidos e superfícies do AutoCAD** (`3DSOLID`, `REGION`, `BODY`, superfícies) não chegam ao arquivo final. A forma deles não é desenho: é um bloco de dados do modelador que, nas versões novas do DXF, fica numa seção separada que o leitor livre de DWG não copia. O que chega aqui é uma casca vazia, e o app avisa quantas foram, em vez de entregar um sucesso silencioso. Medido na fixture `example_2018.dwg`: 2 `REGION` e 1 `3DSOLID` de 66 elementos.
- **Tabelas do AutoCAD** (`ACAD_TABLE`) e objetos de complementos (Architecture, Civil 3D) podem não ser lidos pelo LibreDWG; quando isso acontece a interface diz o quê.
- **Texto de várias linhas vira uma linha por entidade.** É o preço da conversão do item 3: no AutoCAD um parágrafo que era um bloco só passa a ser uma entidade por linha, e editá-lo dá mais trabalho. Em troca, o texto aparece em qualquer programa que abra DXF. A interface informa quantos blocos foram convertidos.
- **O tamanho do desenho na página depende de quem abre.** O DXF guarda as coordenadas do desenho, não um tamanho de papel. O LibreOffice Draw trata cada unidade de desenho como 1 mm, então uma prancha de 30 unidades aparece com uns 3 cm no meio de uma folha grande — é só dar zoom. Um visualizador de CAD ajusta o desenho à tela sozinho. Escalar a geometria para "caber bonito" falsificaria todas as cotas, e por isso o app não faz isso.
- **A imagem da prévia** é só para conferência, a 1600 px no lado maior. O que vale é o DXF.
- **Fontes**: o DXF guarda o *nome* da fonte, não os desenhos das letras — quem abrir o arquivo vê a fonte da própria máquina. Por isso a troca de fonte no servidor afeta **apenas a imagem da prévia**, e o app diz isso com todas as letras em vez de assustar à toa. `static/fonts/` traz a mesma coleção de 181 fontes dos apps irmãos, incluindo a Arial, registrada no leitor **antes** de o desenho ser aberto (ler o desenho já mede o texto, e a primeira medição é que fixa a fonte).
- **Concorrência e disco**: no máximo 2 conversões simultâneas e limpeza de pastas temporárias órfãs, como nos apps irmãos.
- Um DXF renomeado para `.dwg` é reconhecido e saneado sem passar pelo LibreDWG. Arquivos que não são DWG (PDF, ZIP, imagem com o nome trocado) são recusados antes de qualquer conversão.

## 🚀 Rodar localmente

Pré-requisitos: Python 3.10+ e o `dwg2dxf` da LibreDWG.

- **Linux/macOS**: o binário Linux já está em `bin/`. No macOS, instale a LibreDWG (`brew install libredwg`) — o app usa o `dwg2dxf` do PATH.
- **Windows**: baixe `libredwg-0.14-win64.zip` em https://github.com/LibreDWG/libredwg/releases e copie `dwg2dxf.exe` e as DLLs que vêm junto para `bin/` (o `.gitignore` já os ignora).

```bash
pip install -r requirements.txt
streamlit run app.py
```

Abre em `http://localhost:8501`.

## 🧪 Testes

```bash
pip install pytest
pytest -q
```

Cobrem a detecção de versão e de impostores, o resumo de avisos do LibreDWG, o reparo do DXF desalinhado, a ordem de registro das fontes e a conversão de ponta a ponta com os três DWG reais de `tests/fixtures/` (arquivos de teste do próprio projeto LibreDWG). Em cada um deles o arquivo entregue é **reaberto com o leitor estrito** e conferido: versão do DXF preservada e a contagem de elementos batendo com a do desenho lido. Os DXF gerados ficam em `tests/output/`.

Para provar o ambiente de deploy (Debian trixie com os pacotes do `packages.txt`, igual ao Streamlit Cloud):

```bash
docker build --load -f tests/Dockerfile.smoke -t dwg-dxf-smoke . && docker run --rm dwg-dxf-smoke
```

## ☁️ Deploy no Streamlit Cloud

1. Faça push para o GitHub
2. Em [share.streamlit.io](https://share.streamlit.io), conecte o repositório
3. Em **Advanced settings**, escolha **Python 3.13** (ou 3.12). Com Python 3.14 a instalação falha: o Streamlit 1.39 exige pillow abaixo da versão 11, que não tem pacote pronto para 3.14 e não compila na imagem do Cloud. A versão do Python não pode ser trocada depois; é preciso apagar o app e implantar de novo.
4. O `bin/dwg2dxf` é estático e não depende de nada do sistema; o `packages.txt` pede só as fontes
5. Deploy

App no ar: https://dwg-para-dxf.streamlit.app/

## 🔁 Reconstruir o binário do LibreDWG

O `bin/dwg2dxf` foi compilado a partir do código-fonte oficial (release 0.14) com o `bin/build/Dockerfile`:

```bash
cd bin/build
docker build -t libredwg-static .
docker create --name tmp libredwg-static && docker cp tmp:/out/dwg2dxf ../dwg2dxf && docker rm tmp
```

## 📋 Estrutura

```
dwg-para-dxf/
├── app.py              # Aplicação principal
├── requirements.txt    # streamlit, ezdxf, pymupdf
├── packages.txt        # fontes do sistema
├── bin/
│   ├── dwg2dxf         # LibreDWG 0.14, Linux x86_64 estático
│   └── build/          # Dockerfile que gera o binário + licença da LibreDWG
├── static/fonts/       # fontes usadas na prévia
├── tests/              # pytest + fixtures DWG reais
├── NOTICE.md           # Licenças dos componentes
└── README.md
```

## 🛠️ Tecnologias

- **[Streamlit](https://streamlit.io)** — interface web
- **[GNU LibreDWG](https://www.gnu.org/software/libredwg/)** — leitura do DWG
- **[ezdxf](https://ezdxf.mozman.at/)** — leitura, reparo e gravação do DXF
- **[PyMuPDF](https://pymupdf.readthedocs.io/)** — imagem da prévia

## 🔒 Privacidade

Os arquivos são processados em diretórios temporários e removidos após a conversão. Nada é armazenado permanentemente.

---

Desenvolvido com ❤️ usando Python e Streamlit.
