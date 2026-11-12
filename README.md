# Hermes · Painel de Orquestração ao Vivo

Tela que mostra o Hermes orquestrando: cada delegação vira um feixe animado do núcleo
para o especialista, o texto do subagente aparece em streaming no cartão, e o retorno
(verde) marca o resultado recebido.

## Abrir

Com o servidor rodando: **http://127.0.0.1:8791**

- **AO VIVO** — acompanha as delegações em tempo real (lê os arquivos do Hermes a cada ~1s).
- **REPLAY DO DIA** — reexecuta animadamente todas as delegações já registradas.

## Subir o servidor

```powershell
powershell -ExecutionPolicy Bypass -File "D:\sistema para megasena\hermes-live\start_painel.ps1"
```

ou diretamente:

```powershell
python "D:\sistema para megasena\hermes-live\server.py"
```

Para usar outra porta: `$env:PAINEL_PORT=8899` antes de subir.

## O que ele lê (somente leitura)

| Fonte | Uso |
|---|---|
| `%LOCALAPPDATA%\hermes\cache\delegation\live\*\manifest.json` | lotes, tarefas, status |
| `...\live\*\task-N.log` | transcrição ao vivo de cada subagente |
| `...\logs\gateway.log` | eventos (mensagens, respostas, turnos) |
| `...\gateway_state.json` + `state\gateway.heartbeat` | saúde do gateway |
| `...\profiles\*\profile.yaml` | nomes/descrições dos bots |

Nada é escrito no diretório do Hermes.

## Como o bot é escolhido no desenho

O manifesto de delegação não grava o perfil de destino; o painel infere pelo texto do
objetivo (ex.: "arquitetura" → ATLAS, "contrato de API" → TESLA, "requisitos" → ATHENA).
Se não houver palavra-chave, usa o primeiro bot ocioso.

## Arquivos

- `server.py` — servidor HTTP (stdlib, sem dependências).
- `index.html` — painel (SVG + JS puro, sem build).
- `start_painel.ps1` — atalho para subir em background.
- `soul_addendum.md` — regra acrescentada ao SOUL.md do Hermes.
- `demo_prompt.txt` — prompt usado na demonstração.
- `shot*.png` — capturas do painel.
