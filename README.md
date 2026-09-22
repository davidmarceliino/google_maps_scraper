# Buscador de Empresas no Google Maps (sem API)

Ferramenta em Python que pesquisa empresas públicas no **Google Maps** através do
navegador (Playwright), coleta nome, telefone, endereço, cidade, estado, CEP, site e
link do Maps, **retém somente empresas com telefone**, remove duplicatas e exporta
os resultados para **Excel** ou **CSV**.

Não utiliza a Google Maps API. Nenhuma API Key é necessária.

## Executável portátil (.exe) — funciona em qualquer PC

Você pode gerar um **único arquivo `Buscador_Google_Maps.exe`** que embute o Python,
o Flask e o Chromium. Basta **enviar esse arquivo** para qualquer pessoa — ela só
dá dois cliques e a interface abre no navegador, **sem precisar instalar nada**.

Para gerar (na sua máquina, com internet):

```powershell
empacotar_exe.bat
```

Isso cria `Buscador_Google_Maps.exe` na raiz do projeto (cerca de 165 MB). Testado:
o Chromium embutido faz a raspagem normalmente (nome, telefone, endereço, cidade,
estado, CEP e site).

### Como usar no PC de destino

1. Copie apenas o arquivo `Buscador_Google_Maps.exe` para qualquer pasta.
2. Dê dois cliques. O servidor sobe e abre o navegador em `http://localhost:8000`.
3. Feche a janela (ou encerre o processo) para parar.
4. Listas salvas e o perfil do WhatsApp ficam na pasta `dados\` criada ao lado do exe.

> O `.exe` depende apenas do Windows (não usa nenhuma pasta do sistema). Se você
> **editar os seletores do Google Maps** (`scraper.py`) ou o layout web
> (`templates/index.html`), rode `empacotar_exe.bat` novamente para regenerar.

## Estrutura

```
google_maps_scraper/
│
├── main.py          # Ponto de entrada da versão desktop
├── interface.py     # Interface gráfica desktop (CustomTkinter + Tabela)
├── webapp.py        # Servidor web (Flask) para hospedar para a equipe
├── templates/
│   └── index.html   # Interface web (mesmos filtros e exportação)
├── scraper.py       # Automação do navegador com Playwright
├── filters.py       # Regra do telefone obrigatório, dedupe e parsing de endereço
├── exporter.py      # Exportação para Excel (.xlsx) e CSV
├── requirements.txt     # Dependências da versão desktop
├── requirements-web.txt # Dependências da versão web
└── README.md
```

## Dependências

- **Python 3.9+** instalado no Windows.
- Bibliotecas Python: `playwright`, `customtkinter`, `openpyxl`.

## Instalação (Windows)

Abra o **Prompt de Comando** ou **PowerShell** na pasta do projeto:

```powershell
cd google_maps_scraper

python -m venv venv
venv\Scripts\activate

pip install -r requirements.txt
playwright install chromium
```

O comando `playwright install chromium` baixa o navegador Chromium usado na automação
(executar apenas uma vez).

## Execução

```powershell
python main.py
```

## Como usar (desktop)

1. Preencha os filtros:
   - **Nome da empresa** (ex.: `Cantina Bella`)
   - **Segmento / Categoria** (ex.: `Restaurantes`)
   - **Palavra-chave** (opcional)
   - **Cidade ou região** (ex.: `Campinas`)
   - **Quantidade máxima** (1 a 500)
2. Marque **“Somente empresas com telefone”** (ativado por padrão).
3. Clique em **Iniciar busca**. O Chromium abre e pesquisa diretamente no Google Maps.
4. Acompanhe o progresso na tabela. **Parar busca** interrompe a qualquer momento.
5. Ao final, use **Exportar Excel** ou **Exportar CSV**.

O termo de busca é montado automaticamente. Exemplos:

| Filtros                                     | Termo usado            |
| ------------------------------------------- | ---------------------- |
| Barbearias + Campinas                       | `Barbearias em Campinas` |
| Clínicas + Sumaré                           | `Clínicas em Sumaré`     |
| Oficinas + São Paulo                        | `Oficinas em São Paulo`  |
| Restaurantes + Americana                    | `Restaurantes em Americana` |

## Colunas exportadas

```
Nome | Telefone | Endereço | Cidade | Estado | CEP | Site | Google Maps
```

- **CSV** usa separador `;` e codificação UTF-8 com BOM para abrir corretamente no Excel em português.
- **Cidade**, **Estado** e **CEP** são extraídos automaticamente do endereço quando disponíveis.

## Regras de filtragem

- Empresa **sem telefone** → ignorada (regra principal).
- Empresas **duplicadas** → ignoradas (mesmo telefone ou mesmo nome).
- Empresa sem endereço → mantida se tiver telefone, com endereço vazio.
- CAPTCHA / verificação de robô → a busca é encerrada com aviso; **não** há tentativa de contorno.
- Layout do Google Maps muda com frequência → os seletores ficam concentrados em `scraper.py`
  (`_current_items`, `_read_panel`) para facilitar ajustes.

## Tratamento de erros

- Página que não carrega → aviso e encerramento.
- Erro de conexão / elemento não encontrado → avisos na barra de status.
- Interrupção manual (Parar busca / fechar janela) → encerramento limpo.
- Descontrole de resultados (nenhum item novo ao rolar) → aviso.

## Observações

- Coleta somente dados públicos exibidos no Google Maps, para uso pessoal e em escala
  reduzida. Respeite os Termos de Serviço do Google e a legislação local (LGPD).
- Se o Google aplicar CAPTCHA, o script para e avisa — não contorne.
- Se o Google mudar o layout e os resultados pararem de carregar, ajuste os seletores
  no início de `scraper.py`.

---

## Hospedar para sua equipe (versão web)

Se a ideia é deixar a interface disponível para **funcionários usarem pelo navegador**
(no servidor ou numa máquina da empresa), use a versão web (`webapp.py` + Flask).

### Como funciona

- O servidor roda o scraper em **segundo plano** (Chromium headless) e guarda os
  resultados.
- Quem acessa a página dispara a busca, acompanha o progresso em tempo real e baixa
  o Excel/CSV — sem instalar nada na máquina da pessoa.

### Instalação no servidor (Linux/VPS ou Windows)

```powershell
cd google_maps_scraper

python -m venv venv
venv\Scripts\activate          # Linux:  source venv/bin/activate

pip install -r requirements-web.txt

playwright install --with-deps chromium
```

> **Dica:** use Python 3.11 ou 3.12 no servidor (compatibilidade máxima do Playwright).

### Executando

```powershell
python webapp.py
```

Por padrão escuta em **todas as interfaces** na porta **8000**:

```
http://IP_DA_MAQUINA:8000      # acessível pelos funcionários na rede
```

Para mudar porta/host:

```powershell
$env:APP_PORT = "8080"
$env:APP_HOST = "127.0.0.1"    # só acesso local
python webapp.py
```

O servidor usa `waitress` (WSGI) por padrão, seguro para rede local/pequeno uso.

### Rede local (intranet)

- Libere a porta no firewall: Windows → `netsh advfirewall firewall add rule
  name="maps-scraper" dir=in action=allow protocol=TCP localport=8000`.
  Linux → liberar a porta no `ufw`/`firewalld`.

### Internet (fora da empresa)

- Um VPS com **Python + Chromium** (o scraper não precisa de tela, roda headless).
- Aponte um domínio e use HTTPS (recomendado). **A versão atual NÃO tem login** —
  para uso pela internet, coloque um proxy reverso com senha (ex.: Nginx + Basic Auth,
  ou Tunnel Cloudflare com acesso restrito).
- Em VPS Linux rodando como root, o Chromium precisa do `--no-sandbox`, já adicionado
  automaticamente na versão web (`scraper.py`).

### Limites da versão web

- No máximo **2 buscas simultâneas** (evita sobrecarregar o servidor/Google).
- Resultados ficam em memória e são limpos após 6 horas sem uso.
- Sem login/autenticação: use em rede confiável ou proteja com proxy/senha.
- Versão testada com o layout atual do Google Maps (2026); os seletores usados
  (`input[role='combobox']`, `div[role='feed'] div.Nv2PK`, painel com `data-item-id`,
  botão de fechar `[aria-label='Fechar'].VfPpkd-icon-LgbsSe`) ficam no início de
  `scraper.py` caso o Google mude o layout novamente.