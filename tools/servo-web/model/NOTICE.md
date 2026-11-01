# Fonte do modelo

`model.json` + `meshes.bin` foram gerados por `../build_model.py` a partir de [apirrone/microduck_rl](https://github.com/apirrone/microduck_rl), usando `src/mjlab_microduck/robot/microduck/robot_allcollisions.xml` e os arquivos `assets/*.stl` (cópia de 17/09/2026).
Esse repositório usa a licença Apache 2.0. As malhas foram exportadas do CAD oficial do Microduck da Pollen Robotics. O modelo preserva apenas as formas externas visíveis; componentes internos, como placas de circuito e rolamentos, foram removidos.
Os vértices foram quantizados para `int16`.
