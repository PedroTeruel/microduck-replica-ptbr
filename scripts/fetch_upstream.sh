#!/usr/bin/env bash
# Baixa os repositórios upstream. Este repositório guarda apenas resultados gerados e scripts, sem duplicar o código upstream.
set -e
mkdir -p upstream && cd upstream

# Stack de aprendizado por reforço do Microduck: modelo MJCF e 47 arquivos STL.
[ -d microduck_rl ] || git clone --depth 1 https://github.com/pollen-robotics/microduck_rl.git

# Runtime embarcado do Microduck (Rust, para Rockchip RK3566).
[ -d microduck ] || git clone --depth 1 https://github.com/pollen-robotics/microduck.git

# Placa RPI Robot HAT: projeto KiCad oficial de código aberto e arquivos de fabricação (Gerber / BOM / coordenadas de montagem).
[ -d elec_RPI_Robot_HAT ] || git clone --depth 1 https://github.com/pollen-robotics/elec_RPI_Robot_HAT.git

cd ..
echo ""
echo "Concluído. Gere novamente as vistas e a análise da montagem upstream (não são peças para impressão):"
echo "  python scripts/render_assembly.py upstream/microduck_rl assembly-drawings"
echo "  python scripts/export_assembly_stl.py upstream/microduck_rl analysis-output/cad-upstream"
