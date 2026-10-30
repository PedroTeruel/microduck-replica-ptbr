# CAD e modelos mantidos no repositório complementar

**Baixe peças estruturais, conjuntos montados, arquivos-fonte SolidWorks / STEP e projetos de impressão no repositório [fanhao375/microduck-replica-cad](https://github.com/fanhao375/microduck-replica-cad).**

Esse repositório é a fonte única de manutenção dos modelos e contém a seleção de versões, a BOM de montagem, imagens dos componentes e instruções de instalação. Em 2026-09-28, a versão Feetech HD-1910 era a [v2.1](https://github.com/fanhao375/microduck-replica-cad/releases/tag/v2.1), e a versão XL330 era a [v1.1](https://github.com/fanhao375/microduck-replica-cad/releases/tag/v1.1). Antes de baixar, confira o tipo de servo e a versão específica dos acessórios. As recomendações de impressão estão em [print/README](../print/README.md).

Os 16 arquivos STL que ficavam neste diretório eram visualizações de conjuntos geradas a partir do MJCF upstream e não estavam sincronizados com o CAD físico mais recente. Eles foram removidos em 2026-09-28. Se precisar consultá-los, use o histórico do Git; obtenha os arquivos atuais no repositório complementar.

As renderizações de análise em `assembly-drawings/`, os modelos de treinamento e os modelos de depuração web deste repositório ainda podem conter geometrias upstream. Eles não devem ser usados como referência para fabricar ou imprimir as peças estruturais mais recentes. O [script de exportação](../scripts/export_assembly_stl.py) serve apenas para analisar o modelo upstream e, por padrão, grava em `analysis-output/cad-upstream/`, diretório ignorado pelo Git.

**English:** CAD assemblies, mechanical parts and print files now have one maintained source: [microduck-replica-cad](https://github.com/fanhao375/microduck-replica-cad). The old upstream assembly-preview STLs were removed from this directory. Simulation and visualization meshes retained elsewhere are not manufacturing files.
