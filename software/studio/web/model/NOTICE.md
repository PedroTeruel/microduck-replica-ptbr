# Aviso sobre o modelo

`model.json` e `meshes.bin` foram gerados por `../build_model.py` a partir de `src/mjlab_microduck/robot/microduck/robot_allcollisions.xml` e dos arquivos `assets/*.stl` do repositório [apirrone/microduck_rl](https://github.com/apirrone/microduck_rl), usando o snapshot de 2026-09-17. Esse repositório está sob a Apache License 2.0.

A malha foi extraída do CAD oficial do Microduck, da Pollen Robotics. Ela preserva somente a geometria externa visível; componentes internos, como a placa de circuito e os rolamentos, foram removidos. Os vértices foram quantizados em int16.
