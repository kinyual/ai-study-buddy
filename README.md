# AI Study Buddy

**Tagline:** Upload. Learn. Practise. Improve.

AI Study Buddy is planned as a beginner-friendly learning app. It will let a learner register and log in, create multiple-choice quizzes from a chosen topic or from uploaded PDF, DOCX, and TXT study material, answer questions, and review scores, correct answers, explanations, and quiz history.

## Current status

This project is being built in small, approved tasks. Task 2 only adds repository hygiene files: `.gitignore`, `.env.example`, `requirements.txt`, and this README.

Application code, folders, tests, and database files have **not** been added yet. The features described here are the approved target design, not finished functionality.

## Planned architecture

```text
Browser
  |
  | displays pages and forms
Streamlit frontend
  |
  | HTTP requests with Bearer JWT
FastAPI backend
  |
  | validates requests and applies business rules
  |------------------> SQLAlchemy -> SQLite now -> PostgreSQL later
  |
  |------------------> Gemini service -> Google Gemini API
```

- **Streamlit** will be the frontend. It will show login, quiz, and history pages. It will not talk to the database or Gemini directly.
- **FastAPI** will be the backend. It will handle authentication, validation, quiz generation requests, grading, and result storage.
- **SQLite** will be used first for users, submitted results, and per-question review snapshots. The design uses SQLAlchemy and Alembic so PostgreSQL can be introduced later.
- **Google Gemini** will generate quiz questions through a dedicated backend service. The API key will stay on the backend.
- **JWT** will protect private API routes. Passwords will be hashed with Argon2id through `pwdlib[argon2]`.

Big Pickle is the coding assistant used while building this project. Google Gemini is the AI model the finished application will use for quiz generation.

## Prototype data limitation

Active quizzes and temporary uploaded content are held in **backend memory only**. They disappear when the backend restarts, and the initial prototype runs as a **single backend process**.

Submitted quiz results and per-question review snapshots are persisted in **SQLite**, so they survive backend restarts and can be used for review and history.

## Local setup with Windows PowerShell

These commands are provided for later use. No packages are installed by Task 2.

1. Check that Python is available:

```powershell
py --version
```

2. Create a virtual environment:

```powershell
py -m venv .venv
```

3. Activate it:

```powershell
.\.venv\Scripts\Activate.ps1
```

If PowerShell blocks activation, you can allow it for the current session only:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

4. Upgrade pip and install the dependency list:

```powershell
py -m pip install --upgrade pip
py -m pip install -r requirements.txt
```

## Environment variables

Create a local `.env` file from the example file:

```powershell
Copy-Item .env.example .env
```

Then open `.env` and replace the placeholders with your own local values.

Important rules:

- `.env` must never be committed.
- `.env.example` is safe to commit because it contains names and placeholders only.
- `GEMINI_API_KEY` and `JWT_SECRET_KEY` must stay on the backend.
- The Streamlit frontend must never read or display the Gemini API key.

## Tests

`pytest` is included in the dependency list for the planned test suite. Tests will be added in later tasks and will be run before any feature is claimed as working.
