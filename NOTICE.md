# NOTICE

O código deste repositório (`app.py`, testes e documentação) é distribuído sob a licença MIT (ver `LICENSE`).

Este projeto redistribui e depende de componentes de terceiros com licenças próprias:

| Componente | Uso | Licença |
| --- | --- | --- |
| **GNU LibreDWG 0.14** (`bin/dwg2dxf`) | binário compilado a partir do código-fonte oficial, sem modificações, executado como processo separado | GPL-3.0-or-later — texto em `bin/build/COPYING-LibreDWG`; código-fonte em https://github.com/LibreDWG/libredwg/releases/tag/0.14; receita de compilação em `bin/build/Dockerfile` |
| **ezdxf** | leitura, reparo e gravação do DXF | MIT |
| **PyMuPDF** (MuPDF) | imagem da prévia na tela | AGPL-3.0 (Artifex). O uso comercial sem disponibilizar o código-fonte exige licença comercial da Artifex |
| **Streamlit** | interface web | Apache-2.0 |
| **Fontes** (`static/fonts/`) | fontes que o leitor usa para desenhar os textos na imagem da prévia, já que o servidor não tem nenhuma. Mesma coleção dos apps irmãos do autor: Liberation, DejaVu, Carlito, Noto e fontes de sistema como Arial e Impact | famílias livres sob SIL OFL 1.1, Bitstream Vera e Apache-2.0 (texto da DejaVu em `static/fonts/LICENSE_DEJAVU`); as fontes de sistema entram só para fidelidade da prévia e seguem os termos de seus fabricantes |

Os arquivos DWG em `tests/fixtures/` vêm da suíte de testes do projeto LibreDWG (`test/test-data/`) e são usados apenas para verificação automatizada.

AutoCAD e DWG são marcas da Autodesk, Inc. Este projeto não é afiliado à Autodesk.
