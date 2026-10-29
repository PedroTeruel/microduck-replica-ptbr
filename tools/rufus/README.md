# Rufus · ferramenta para gravar cartões no Windows

[Voltar ao índice de ferramentas](../README.md) · [Gravação e primeiro uso](../../software/image/烧录和第一次使用.md)

Use esta ferramenta para gravar a imagem do pato em um cartão microSD. Aqui fornecemos a versão oficial original **Rufus 4.15 portátil para Windows x64**, que não requer instalação.

**[Baixar rufus-4.15p.exe](rufus-4.15p.exe)** · [Página oficial de versões](https://github.com/pbatard/rufus/releases/tag/v4.15) · [Outras plataformas e versão mais recente](https://rufus.ie/zh/)

## Como gravar o cartão

1. Baixe a imagem do pato no formato .img.xz, insira o cartão microSD no leitor e conecte-o ao computador.
2. Abra o Rufus e, em “Dispositivo”, confira a capacidade e a letra da unidade do cartão SD. **A gravação apagará os dados do cartão selecionado.**
3. Clique em “Selecionar” e escolha o arquivo de imagem. Se o filtro não mostrar arquivos .img.xz, altere-o para “Todos os arquivos”.
4. Confira novamente o cartão de destino, clique em “Iniciar” e aguarde o estado voltar a “Pronto”. Depois, ejete o leitor com segurança.
5. Se o Windows pedir para formatar uma partição Linux, clique em “Cancelar”. Coloque o cartão no pato e siga as [instruções da primeira inicialização e configuração da rede](../../software/image/烧录和第一次使用.md#3-第一次开机).

## Origem e verificação

A publicação oficial foi conferida em 25/10/2026. O SHA256 do executável é igual ao do arquivo publicado no GitHub; a assinatura digital do Windows é válida e está em nome de Akeo Consulting. O arquivo baixado não foi modificado.

| Arquivo | Finalidade |
|---|---|
| [rufus-4.15p.exe](rufus-4.15p.exe) | Versão portátil para Windows x64 |
| [rufus-4.15-source.zip](rufus-4.15-source.zip) | Código-fonte oficial da mesma versão, com arquivos de construção e licenças dos componentes |
| [LICENSE.txt](LICENSE.txt) | Licença GPL-3.0-or-later do Rufus |
| [SHA256SUMS.txt](SHA256SUMS.txt) · [SOURCE.json](SOURCE.json) | Hashes, origem dos downloads e registro da versão |

No PowerShell, execute Get-FileHash .\\rufus-4.15p.exe -Algorithm SHA256 e compare o resultado com SHA256SUMS.txt para conferir o arquivo.

O autor do Rufus é Pete Batard / Akeo Consulting. O código-fonte e as atualizações são mantidos em [pbatard/rufus](https://github.com/pbatard/rufus).
