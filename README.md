<div align="center">
  <img src="https://raw.githubusercontent.com/nickkcj/soundscore-frontend/main/public/images/logo_soundscore.png" alt="SoundScore Logo" width="200" />

  # API

  **The high-performance core for the SoundScore social network.**

  [![FastAPI](https://img.shields.io/badge/FastAPI-005571?style=for-the-badge&logo=fastapi)](https://fastapi.tiangolo.com/)
  [![AWS](https://img.shields.io/badge/AWS-232F3E?style=for-the-badge&logo=amazon-aws)](https://aws.amazon.com/)
  [![PostgreSQL](https://img.shields.io/badge/PostgreSQL-4169E1?style=for-the-badge&logo=postgresql)](https://www.postgresql.org/)

  [Live Site](https://soundscore.com.br) • [Frontend Repo](https://github.com/nickkcj/soundscore-web)
</div>

---

## Overview

SoundScore is a community-driven platform designed to bridge the gap between music streaming and social interaction. It allows users to document their listening habits through real-time data synchronization and engage in deep musical discussions powered by AI-driven insights.

---

## Key Features

- **Album Reviews:** Full CRUD for rating and writing long-form album reviews.
- **Social Graph:** Robust follow system to track friend activity and global music trends.
- **Real-time Interaction:** Group discussion hubs powered by **WebSockets**.
- **Spotify Synchronization:** Automated scrobbling and listening history integration.
- **AI-Powered Insights:** Integrated **Google Gemini** chatbot for natural language queries about the database.
- **Dynamic Social Feed:** Real-time updates and notifications delivered via **SSE (Server-Sent Events)**.

---

## Tech Stack

### Backend Core
- **FastAPI**: Asynchronous Python framework focused on high performance and type safety.
- **SQLAlchemy 2.0**: Advanced async ORM for relational data management.
- **Alembic**: Database versioning and migration management.
- **Pydantic V2**: Modern data validation and serialization.

### Data & Cache
- **PostgreSQL (Amazon RDS)**: Primary relational storage.
- **Redis**: Low-latency caching and WebSocket state management.

### Security
- **JWT (JSON Web Tokens)**: Stateless authentication with secure access/refresh logic.
- **OAuth 2.0**: Social login integration for **Google** and **Spotify**.
- **Passlib/Bcrypt**: Industry-standard secure password hashing.

---

## Architecture & Design Patterns

The project implements a **Layered Architecture** to ensure clean separation of concerns:

1.  **Routers (API Layer):** Handles HTTP/WebSocket requests and input validation.
2.  **Services (Business Layer):** Contains core logic, external API integrations, and AI orchestration.
3.  **Models (Data Layer):** Defines the relational schema and database interactions.
4.  **Schedulers:** Background workers for automated data sync.

**Key Optimizations:**
- **Asynchronous I/O:** Fully non-blocking architecture using `async/await`.
- **N+1 Prevention:** Strategic use of batch queries and joined loads to minimize database roundtrips.
- **Resilient Clients:** Global HTTP client with connection pooling for external integrations.

---

## Cloud Infrastructure (AWS)

The platform is architected for scalability and cost-efficiency using a modern AWS stack:

- **Amazon EC2**: Hosts the containerized FastAPI application via Docker.
- **Amazon RDS (PostgreSQL)**: Fully managed relational database with automated backups and scaling.
- **AWS Lambda**: Executes scheduled tasks (cron jobs) for Spotify scrobble synchronization, reducing 24/7 compute costs.
- **Amazon S3**: High-durability storage for user-generated content, profile images, and group media.

---

## Project Structure

```text
soundscore-api/
├── alembic/                # Database migrations and versioning
├── app/                    # Main application package
│   ├── core/               # Security, global config, and exceptions
│   ├── models/             # SQLAlchemy relational models
│   ├── routers/            # API endpoints and controllers
│   ├── schemas/            # Pydantic validation/DTO models
│   ├── services/           # Business logic and external API clients
│   ├── utils/              # Batch query helpers and utilities
│   ├── websockets/         # Real-time communication managers
│   └── database.py         # RDS connection and session factory
├── Dockerfile              # Container specification
└── main.py                 # Application entry point
```

---

## Setup & Installation

### Prerequisites
- Python 3.12+
- Docker & Docker Compose
- AWS CLI (for production deployment)

### Local Development

1. **Clone and Setup:**
   ```bash
   git clone https://github.com/nickkcj/soundscore-api.git
   cd soundscore-api
   python -m venv venv
   source venv/bin/activate # or venv\Scripts\activate on Windows
   pip install -r requirements.txt
   ```

2. **Environment Variables:**
   Copy `.env.example` to `.env` and configure your keys (Spotify API, Google Gemini, AWS Credentials, etc.).

3. **Database Migrations:**
   ```bash
   alembic upgrade head
   ```

4. **Run Application:**
   ```bash
   uvicorn app.main:app --reload
   ```

---

## API Documentation

Once the server is running, the interactive documentation is available at:
- **Swagger UI:** `http://localhost:8000/docs`
- **ReDoc:** `http://localhost:8000/redoc`
