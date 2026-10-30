# Teste curto local

Comece com **caminhada em piso plano HD1910 → 64 ambientes → 5 iterações**. O botão “Iniciar teste curto” usa esses parâmetros automaticamente e salva um checkpoint por iteração. O mecanismo de treinamento coleta 24 passos por ambiente em cada iteração, totalizando `64 × 24 × 5 = 7.680` amostras. A contagem do log começa em 0; o último arquivo é `model_4.pt`.

## Pela interface

1. Inicie o serviço real de treinamento e abra o endereço exibido. Em “Ambiente de computação”, confirme o modo real, CUDA, o backend gráfico e a verificação das tarefas.
2. Clique em “Novo treinamento”, selecione “Caminhada em piso plano HD1910”, informe o nome do experimento e clique em “Iniciar teste curto”. Mantenha a semente e a taxa de aprendizado padrão nesta primeira execução.
3. Aguarde o estado “Concluído”. Devem aparecer cinco pontos de métricas, os arquivos `model_0.pt` a `model_4.pt` e um total de 7.680 passos no log.
4. Avalie o último checkpoint, `model_4.pt`, e confira a reprodução da política por 250 passos, com cerca de cinco segundos. A visualização CAD da área de treinamento tem finalidade diferente do vídeo de avaliação.
5. Exporte o pacote do modelo e confirme que o download foi concluído. Antes de implantá-lo, confira o modelo e a configuração do robô e faça uma validação de simulação separada.

Cinco iterações servem para verificar o carregamento, a simulação na GPU, a atualização do otimizador e o fluxo de geração dos artefatos. Recompensas negativas, quedas do pato ou movimentos instáveis não bastam para concluir que o teste curto falhou. O foco é terminar sem erros, manter métricas finitas, carregar um checkpoint de verificação e reproduzir o vídeo. Faça esse teste antes de iniciar um treinamento longo.

## Windows com WSL2

O serviço real de treinamento é executado no Linux; o Windows hospeda a interface no navegador. É necessário ter um driver NVIDIA compatível com CUDA no WSL, conseguir ver a GPU com `nvidia-smi` dentro do WSL e ter Python 3.12 e uv instalados. Execute os comandos abaixo na raiz do projeto dentro do WSL:

```sh
export PATH="$HOME/.local/bin:$PATH"
cd software/training
uv sync --frozen --python 3.12
cd ../training-studio
../training/.venv/bin/python run.py --port 8094
```

Depois, abra <http://127.0.0.1:8094> no navegador do Windows. A porta 8094 diferencia esse serviço da demonstração padrão, que usa 8093. Não inicie o serviço com `--demo`.

O backend gráfico padrão é EGL, usado tanto na verificação do ambiente quanto no treinamento e na avaliação. No Ubuntu 22.04, se faltar `libEGL.so.1`, instale o pacote de sistema `libegl1` e execute a verificação novamente. O valor definido explicitamente para `MUJOCO_GL` é mantido; prepare também as dependências de sistema do backend selecionado. A verificação prévia confirma apenas se a biblioteca gráfica pode ser carregada; valide a renderização real pelo vídeo de avaliação da política.

O primeiro registro de todas as tarefas pode levar algumas dezenas de segundos; a verificação aceita até 60 segundos. Fechar a página não encerra o serviço. Fechar o terminal que está executando `run.py` encerra as tarefas iniciadas por ele. Antes de mudar o diretório de inicialização ou de registros, preserve tanto o log do mecanismo de treinamento quanto o estado salvo pelo serviço.

## Execução verificada

Em 23/10/2026, no Windows com WSL Ubuntu 22.04, RTX 5060 Ti de 16 GB, Python 3.12.14, torch 2.9.1+cu128 e mjlab 1.3.0, as cinco iterações descritas acima terminaram em cerca de 41 segundos, incluindo o carregamento inicial, e geraram cinco arquivos PT. A avaliação produziu um vídeo de 960×540, 50 FPS e 250 quadros. O checker ONNX e a comparação de inferência PT/ONNX com 32 conjuntos de entradas iguais também passaram. O tempo é o medido nessa execução; a compilação inicial do kernel e outras máquinas podem alterar o resultado.
