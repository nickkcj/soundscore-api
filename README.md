# SoundScore API

Backend da plataforma SoundScore - uma rede social para amantes de musica avaliarem e compartilharem suas opinioes sobre albuns.

**Acesse:** [https://soundscore.com.br](https://soundscore.com.br)

---

## Sumario

- [Objetivo do Projeto](#objetivo-do-projeto)
- [Stack Tecnologica](#stack-tecnologica)
- [Arquitetura](#arquitetura)
- [Organizacao de Pastas](#organizacao-de-pastas)
- [Configuracao e Instalacao](#configuracao-e-instalacao)
- [Execucao](#execucao)
- [Deploy](#deploy)

---

## Objetivo do Projeto

O SoundScore e uma plataforma social voltada para entusiastas de musica, permitindo que usuarios:

- Avaliem e escrevam reviews de albuns musicais
- Sigam outros usuarios e acompanhem suas avaliacoes
- Participem de grupos de discussao com chat em tempo real
- Acompanhem seu historico de reproducao (scrobbling) via integracao com Spotify
- Interajam com um chatbot de IA para consultas sobre o banco de dados
- Descubram novos albuns atraves de rankings e tendencias

---

## Stack Tecnologica

### Backend Framework
- **FastAPI** - Framework web assincrono de alta performance
- **Uvicorn** - Servidor ASGI para producao

### Banco de Dados
- **PostgreSQL** - Banco de dados relacional principal
- **SQLAlchemy 2.0** - ORM assincrono com suporte a async/await
- **Alembic** - Migracao de schema do banco de dados
- **asyncpg** - Driver PostgreSQL assincrono

### Cache e Mensageria
- **Redis** - Cache de dados e gerenciamento de sessoes WebSocket

### Autenticacao e Seguranca
- **JWT (python-jose)** - Tokens de acesso e refresh
- **Passlib + bcrypt** - Hash de senhas
- **Authlib** - OAuth 2.0 (Google e Spotify)

### Integracao Externa
- **Spotify Web API** - Busca de albuns e scrobbling
- **Google Gemini** - Chatbot de IA para consultas
- **Supabase Storage** - Armazenamento de imagens (perfil, grupos)
- **Resend** - Envio de emails transacionais

### Comunicacao em Tempo Real
- **WebSockets** - Chat de grupos em tempo real
- **Server-Sent Events (SSE)** - Notificacoes em tempo real

### Infraestrutura
- **Docker** - Containerizacao
- **Railway** - Plataforma de deploy

---


## Organizacao de Pastas

```
soundscore-api/
|
|-- alembic/                    # Migracao de banco de dados
|   |-- versions/               # Arquivos de migracao
|   |-- env.py                  # Configuracao do Alembic
|   |-- script.py.mako          # Template de migracao
|
|-- app/                        # Codigo principal da aplicacao
|   |
|   |-- core/                   # Modulos centrais
|   |   |-- exceptions.py       # Excecoes HTTP customizadas
|   |   |-- security.py         # Autenticacao JWT e hash de senhas
|   |
|   |-- models/                 # Modelos SQLAlchemy (ORM)
|   |   |-- user.py             # Usuario e relacionamento de follows
|   |   |-- review.py           # Album, Review, Comment, Likes
|   |   |-- group.py            # Grupos, membros, mensagens, convites
|   |   |-- feed.py             # Notificacoes
|   |   |-- chatbot.py          # Historico do chatbot
|   |   |-- oauth.py            # Contas OAuth vinculadas
|   |   |-- scrobble.py         # Historico de reproducao
|   |
|   |-- routers/                # Endpoints da API (Controllers)
|   |   |-- auth.py             # Autenticacao (registro, login, senha)
|   |   |-- users.py            # Perfil, follows, sugestoes
|   |   |-- reviews.py          # CRUD de reviews, comentarios, likes
|   |   |-- feed.py             # Feed social e notificacoes
|   |   |-- groups.py           # Grupos e convites
|   |   |-- chatbot.py          # Chatbot de IA
|   |   |-- home.py             # Endpoints publicos (landing page)
|   |   |-- oauth.py            # OAuth Google e Spotify
|   |   |-- library.py          # Scrobbling e estatisticas
|   |
|   |-- schemas/                # Schemas Pydantic (validacao/serializacao)
|   |   |-- auth.py             # Schemas de autenticacao
|   |   |-- user.py             # Schemas de usuario
|   |   |-- review.py           # Schemas de review e album
|   |   |-- feed.py             # Schemas de notificacao
|   |   |-- group.py            # Schemas de grupo
|   |   |-- chatbot.py          # Schemas do chatbot
|   |   |-- library.py          # Schemas de scrobbling
|   |   |-- oauth.py            # Schemas OAuth
|   |
|   |-- services/               # Camada de servicos (logica de negocio)
|   |   |-- cache_service.py    # Gerenciamento de cache Redis
|   |   |-- spotify_service.py  # Integracao Spotify (busca)
|   |   |-- spotify_scrobble_service.py  # Scrobbling Spotify
|   |   |-- gemini_service.py   # Chatbot com Google Gemini
|   |   |-- storage_service.py  # Upload de imagens (Supabase)
|   |   |-- notification_service.py  # Criacao de notificacoes
|   |   |-- email_service.py    # Envio de emails (Resend)
|   |   |-- oauth_service.py    # Configuracao OAuth
|   |   |-- recommendation_service.py  # Sugestoes de usuarios
|   |   |-- http_client.py      # Cliente HTTP global com pooling
|   |   |-- scrobble_scheduler.py  # Agendador de sync automatico
|   |
|   |-- utils/                  # Utilitarios
|   |   |-- batch_queries.py    # Queries em batch (evita N+1)
|   |
|   |-- websockets/             # WebSocket handlers
|   |   |-- manager.py          # Gerenciador de conexoes
|   |   |-- group_chat.py       # Chat de grupo em tempo real
|   |
|   |-- config.py               # Configuracoes da aplicacao
|   |-- database.py             # Conexao com banco de dados
|   |-- dependencies.py         # Dependencias FastAPI (auth, db)
|   |-- main.py                 # Ponto de entrada da aplicacao
|
|-- .env.example                # Exemplo de variaveis de ambiente
|-- .gitignore                  # Arquivos ignorados pelo Git
|-- .dockerignore               # Arquivos ignorados pelo Docker
|-- alembic.ini                 # Configuracao do Alembic
|-- Dockerfile                  # Imagem Docker
|-- railway.toml                # Configuracao Railway
|-- requirements.txt            # Dependencias Python
```

---

## Configuracao e Instalacao

### Pre-requisitos
- Python 3.12+
- PostgreSQL 15+
- Redis 7+

### Instalacao Local

```bash
# Clone o repositorio
git clone https://github.com/seu-usuario/soundscore-api.git
cd soundscore-api

# Crie um ambiente virtual
python -m venv venv
source venv/bin/activate  # Linux/Mac
# ou
venv\Scripts\activate     # Windows

# Instale as dependencias
pip install -r requirements.txt

# Configure as variaveis de ambiente
cp .env.example .env
# Edite o arquivo .env com suas credenciais

# Execute as migracoes
alembic upgrade head

# Inicie o servidor
uvicorn app.main:app --reload
```

---



---

## Execucao

### Desenvolvimento
```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### Producao (Docker)
```bash
docker build -t soundscore-api .
docker run -p 8000:8000 --env-file .env soundscore-api
```

### Documentacao da API
Apos iniciar o servidor, acesse:
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

---

## Deploy

O projeto esta configurado para deploy no Railway:

1. Conecte o repositorio ao Railway
2. Configure as variaveis de ambiente
3. O deploy e automatico via Dockerfile

Configuracoes de deploy estao em `railway.toml`:
- Health check em `/health`
- Restart automatico em caso de falha
- Maximo de 3 tentativas de restart
