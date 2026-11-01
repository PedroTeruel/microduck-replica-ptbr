"""Ponto de entrada do Studio: python3 -I run.py [args]

Ao iniciar com -I (modo isolado), o Python não inclui pacotes do diretório atual nem do diretório do usuário.
Esse é o comportamento desejado (usar somente as dependências fixadas em deps/), mas `-m studio` deixa de localizar o pacote.
Por isso, este arquivo coloca deps/ e o diretório do Studio no início do caminho antes de iniciar o aplicativo.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.join(HERE, "deps"), HERE]

from studio.__main__ import main  # noqa: E402

if __name__ == "__main__":
    main()
