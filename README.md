# VortexTorrent

Cliente BitTorrent desktop de alta velocidade para Windows, construido com núcleo C++ **libtorrent 2.1.1** (via Python 3.13), interface desktop **Electron + React + TypeScript** em tema escuro e otimizações agressivas de rede, disco e conclusão de swarm.

## Principais vantagens de desempenho

1. **Núcleo C++ `libtorrent 2.1.1` com perfil Turbo Max**: rampa inicial de até 500 tentativas de conexão por segundo, 1200 conexões globais, fila de pedidos ampliada (2500/3000) e buffers de socket de 4 MB para saturar links de alta velocidade.
2. **TCP prioritário sobre uTP (`prefer_tcp`)**: evita redução prematura de banda causada pelo algoritmo de latência LEDBAT do uTP.
3. **Turbo Staging em NVMe**: quando o destino final é um HDD mecânico (`D:`), o download grava primeiro em uma pasta de staging no SSD/NVMe (`C:\VortexStaging`) sem sofrer com escritas aleatórias de HDDs SMR e move o arquivo completo de forma sequencial ao término.
4. **Anti-Stall Endgame Booster**: monitora queda brusca de velocidade nos últimos 8% do download e prioriza deadlines de peças faltantes com reanúncio imediato para evitar travamento em 99%.
5. **Hash paralelo com aceleração por hardware**: threads dedicadas para `hashing_threads` e `aio_threads` aproveitando instruções SHA-NI do processador.
6. **Boost inteligente de trackers públicos**: injeta trackers públicos ativos apenas em torrents públicos, bloqueando estritamente qualquer injeção quando a flag `private` estiver ativa.
7. **Telemetria e diagnóstico em tempo real**: painel ao vivo de fila de disco, eficiência payload vs overhead, nós DHT e detecção automática de gargalo.

## Estrutura do projeto

- `engine/`: backend FastAPI + WebSocket + motor `libtorrent 2.1.1`.
- `ui/`: interface React 19 + Vite + TypeScript em tema escuro.
- `desktop/`: shell Electron com janela integrada, bandeja do sistema, notificações nativas e captura de `magnet:`/`.torrent`.
- `scripts/`: scripts de setup, execução, desenvolvimento, geração de ícones e integração com o Windows (`HKCU`).

## Como executar

1. Setup completo (venv Python, build da UI e Electron):
   ```powershell
   powershell -ExecutionPolicy Bypass -File .\scripts\setup.ps1
   ```
2. Iniciar aplicativo desktop:
   ```powershell
   powershell -ExecutionPolicy Bypass -File .\scripts\start.ps1
   ```
3. Modo desenvolvimento (Vite hot reload + Electron):
   ```powershell
   powershell -ExecutionPolicy Bypass -File .\scripts\dev.ps1
   ```
4. Rodar testes e benchmark local:
   ```powershell
   .\engine\.venv\Scripts\python.exe -m pytest -v -s .\engine\tests\test_engine.py
   ```
