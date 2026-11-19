# Contribuindo com o Nexo Torrent

O Nexo Torrent é um cliente BitTorrent open source sob licença MIT focado em desempenho máximo de rede, I/O em disco e verificação paralela. Toda contribuição que reduza latência, melhore a taxa real de transferência ou aprimore a inspeção de swarm é bem-vinda.

## Preparando o ambiente local

1. Instale Python 3.13+ e Node.js 20+ (com npm).
2. Execute o setup completo na raiz do repositório:
   ```powershell
   powershell -ExecutionPolicy Bypass -File .\scripts\setup.ps1
   ```
3. Para desenvolvimento da interface com hot reload:
   ```powershell
   powershell -ExecutionPolicy Bypass -File .\scripts\dev.ps1
   ```

## Padrões obrigatórios

1. Execute a suíte de testes após qualquer alteração no motor:
   ```powershell
   .\engine\.venv\Scripts\python.exe -m pytest -v .\engine\tests\test_engine.py
   ```
2. Garanta build limpo da interface React/TypeScript:
   ```powershell
   Push-Location .\ui
   npm run build
   Pop-Location
   ```
3. Mudanças de desempenho no `engine/` devem incluir medição comparativa reproduzível via `scripts/benchmark.py`:
   ```powershell
   .\engine\.venv\Scripts\python.exe .\scripts\benchmark.py --scenarios all --size-mb 512 --live-seconds 25
   ```
4. Mantenha a compatibilidade de UI 100% em português do Brasil (pt-BR), seguindo os tokens visuais NEXO Mineral definidos em `ui/src/styles.css`, sem caminhos absolutos pessoais no código e sem telemetria.
5. Nunca habilite injeção de trackers públicos em torrents marcados com `priv == True` (BEP 27).
