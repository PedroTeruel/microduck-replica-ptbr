# Gerenciamento de modelos no Studio

O usuário aprovou o UI-08 e, em 22/10/2026, solicitou explicitamente o início da implementação. O objetivo é instalar no pato modelos treinados e exportados no computador, permitir seleção, nomeação, remapeamento dos botões do controle, exclusão e restauração do padrão, sem exigir que o usuário grave novamente a imagem do sistema.

## Fluxo de uso

A opção “Gerenciar” do painel geral abre diretamente a rota de modelos. No topo ficam o botão de importação e uma explicação breve. A lista distingue modelos padrão integrados dos importados e mostra nome, finalidade, se está selecionado ou em execução e os botões associados. A instalação não ativa o modelo nem habilita torque automaticamente. Caminho, hash e detalhes do treinamento ficam recolhidos. Peso e exportação do perfil do pato permanecem na página de configurações existente, fora do gerenciamento de modelos.

A importação aceita um diretório de implantação exportado, compactado em ZIP ou tar.gz: policy.onnx, manifest.json, deployment-contract.json e, opcionalmente, a configuração de execução específica do modelo. Antes da instalação, valida os limites do perfil, a identidade dos arquivos, a finalidade e a pré-verificação do ONNX real pelo programa principal. Se falhar, o pacote não aparece na lista de modelos disponíveis. O nome pode ser editado; não é permitido sobrescrever arquivos do sistema nem modelos existentes.

A seleção reutiliza robot.loadPolicy. O sucesso é confirmado pela leitura de retorno de robot.policies; uma resposta accepted não basta. Se falhar, tenta restaurar o caminho anterior e informa honestamente o resultado da reversão. O caminho do modelo integrado básico é salvo como fonte padrão de restauração, para que um reset genérico custom_only não aponte por engano para outro modelo oficial.

Os botões disponíveis no programa principal atual são A, X, LB, RB e direcional para baixo. Reutiliza pad.bind; para desvincular, envia uma string vazia; para restaurar o padrão, usa a semântica nativa de omitir skill. Em caso de conflito, mostra explicitamente a ação existente; só grava depois de o usuário escolher substituí-la. Ação e finalidade do modelo são conceitos separados: caminhada não é uma habilidade comum acionada por um botão.

Modelos importados pelo usuário podem ser excluídos. Se o modelo ainda estiver associado a um slot ou a um botão, primeiro exige explicitamente que o usuário troque a seleção ou restaure o padrão, evitando referências pendentes. Arquivos integrados não oferecem opção de exclusão. Recusa a troca enquanto houver movimento ou antes da confirmação de que o torque foi desativado; preserva a parada de emergência e os controles básicos existentes.

## Arquitetura

- Todos os arquivos importados ficam em state/models, gravável pelo usuário do Studio; padrão: /var/lib/microduck-studio/models. Não é necessário ampliar as permissões do helper root.
- model_package.py: extração segura do pacote, validação estática do contrato e chamada de robotd validate-policy; não se conecta ao hardware.
- models.py: metadados da biblioteca, fonte padrão, instalação, renomeação, exclusão, RPC para o executor e confirmação por leitura de retorno.
- app.py: endpoints HTTP da mesma origem, após validação de sessão/CSRF; limita tamanho dos envios em fluxo e serializa alterações.
- models.js: página de gerenciamento independente. O cartão do painel geral em tune.js passa a apontar para essa página.

## Contrato HTTP

GET /api/models retorna {ok:true,data:View}; POST /api/models/import recebe os bytes originais de ZIP/tar.gz e os parâmetros de URL filename e name (opcional), exigindo X-CSRF. POST /api/models/op recebe até 32 KiB de JSON e também exige X-CSRF.

Operações: rename{id,name}, select{id,slot}, restore{slot}, delete{id}, bind{button,slot,replace?}, unbind{button} e reset_bindings{}.

Em caso de sucesso, retorna {ok:true,data:View}. Em caso de falha, retorna {ok:false,error:motivo em texto,code:identificador opcional}; escolhe HTTP 400/409/413/503 conforme o erro real. ModelError representa uma exceção prevista na camada de serviço.

View contém:

```
{
 items:[{id,name,source:'builtin'|'imported',task,suggested_slot,slots:[],running:false,
         buttons:[],can_delete:false,reason:null,sha12,installed:true}],
 slots:[{slot,label,model_id,path,error,default_id}],
 bindings:[{button,label,slot,skill,model_id,default_skill}],
 capabilities:{import:false,select:false,reason:null},
 buttons:[{button,label}],
 error:null
}
```

Models(rd,log,state_dir,tune=None,root='/',validator=None,rpc=None) fornece async view(), import_package(path,name='') e handle(args,by=None). O teste pode injetar validator e rpc; em produção, usa o caminho confiável fixo do robotd e o socket real. O modo de teste/demonstração não pode apresentar um sucesso simulado como confirmação de produção.

## Validação e entrega

Primeiro, escrever casos de falha e depois implementar os caminhos críticos de leitura e escrita. Pacotes com traversal, links, caminhos duplicados, tamanho excessivo, hash inválido ou incompatibilidade devem ser recusados; uma falha temporária não pode deixar instalação parcial. Modelos padrão não podem ser excluídos, e modelos referenciados também não; a seleção e as mudanças de botões precisam de confirmação por leitura de retorno e devem reverter em caso de falha. Validar por HTTP sessão, Origin, CSRF e limites de tamanho; usar navegador sem interface para verificar entrada do gerenciamento, importação, nomeação, seleção, remapeamento, exclusão e restauração. Não enviar comandos de movimento ao robô real nem trocar o modelo do controle ativo; a implantação e o carregamento reais devem ser conferidos separadamente conforme o estado atual.
