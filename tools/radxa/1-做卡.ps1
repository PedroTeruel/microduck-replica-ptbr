# Criar cartão com um clique (Windows): chama build-armbian-card.sh pelo WSL, gera xxx-cartao-microduck.img e grava com Rufus.
# Uso: edite card.conf no mesmo diretório (nome/senha do Wi-Fi), clique com o botão direito neste arquivo e escolha Executar com PowerShell; selecione o .img.xz do Armbian.
# É necessário instalar WSL2 (no PowerShell como administrador, execute wsl --install e reinicie). A execução deste script não requer privilégios de administrador.
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
if ((Get-Content (Join-Path $PSScriptRoot 'card.conf') -Raw) -match 'ALTERE_PARA_') { Write-Host 'Altere o nome e a senha do Wi-Fi em card.conf' -ForegroundColor Red; Read-Host 'Pressione Enter para sair'; exit 1 }
$dlg = New-Object System.Windows.Forms.OpenFileDialog
$dlg.Filter = 'Imagem Armbian (*.img.xz)|*.img.xz'; $dlg.Title = 'Selecione Armbian_26.2.1_Radxa-zero3_trixie_vendor_6.1.115_minimal.img.xz'
if ($dlg.ShowDialog() -ne 'OK') { exit }
function ToWsl($p) { '/mnt/' + $p.Substring(0,1).ToLower() + $p.Substring(2).Replace('\','/') }
$distro = ((wsl -l -q) -replace "`0", '' | Where-Object { $_ -and $_ -notlike 'docker-desktop*' } | Select-Object -First 1)
if (-not $distro) { Write-Host 'Nenhuma distribuição Linux encontrada no WSL. No PowerShell como administrador, execute wsl --install e reinicie.' -ForegroundColor Red; Read-Host 'Pressione Enter para sair'; exit 1 }
$env:WSL_UTF8 = 1
wsl -d $distro.Trim() -u root -- bash (ToWsl (Join-Path $PSScriptRoot 'build-armbian-card.sh')) (ToWsl $dlg.FileName) (ToWsl (Join-Path $PSScriptRoot 'card.conf'))
if ($LASTEXITCODE -eq 0) { Write-Host "`nConcluído. No Rufus, selecione a imagem -cartao-microduck.img gerada." -ForegroundColor Green } else { Write-Host "`nFalha. Compartilhe a saída acima para receber ajuda." -ForegroundColor Red }
Read-Host 'Pressione Enter para sair'
