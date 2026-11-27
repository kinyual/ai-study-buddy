# AI Study Buddy

**Tagline:** Upload. Learn. Practise. Improve.

## 1. Problem

Students and trainees struggle to make relevant practice questions from
their study materials and rarely get instant feedback on what they know.
Writing quizzes by hand takes time.

## 2. Target Users

Students, trainees, professionals in training and independent learners,
using a laptop or phone browser with normal internet.


## 3. MVP User Stories

1. **Register and log in:** As a learner, I want to create an account, log in, and log out securely so that I can access my personal learning space.
2. **Start a quiz:** As a learner, I want to choose whether to create a quiz from uploaded study material or enter a topic so that I get a quiz without uploading anything.
3. **Upload study material:** As a learner, I want to upload PDF, DOCX, or TXT files so the app can extract their text for quiz generation.
4. **Configure and practise:** As a learner, I want to select difficulty (Easy, Medium, Hard), question count (5, 10, 15), generate multiple-choice questions.
5. **Review results:** As a learner, I want to answer, submit and see my score, percentage, correct answers, explanations, and previous quiz results, and have an opportunity to try another quiz.


## 4. Quiz Requirements

- Support two quiz modes: uploaded study material and a topic.
- Support PDF, DOCX, and TXT uploads.
- Validate file type and size.
- Extract text and check whether enough useful content is available.
- Allow learners to preview extracted content and, where practical, select a section.
- Questions generated from uploaded material must be grounded in that material.
- Topic-based questions may use the AI model's general knowledge.
- Each question must have four options and one correct answer.
- Include explanations and avoid duplicate questions.
- Show results and revision feedback after submission.


## 5. Out of Scope for the Initial Prototype

- Payments and subscriptions
- Social sharing
- Long-term performance tracking
- Complex dashboards and advanced analytics


## 6. AI Feature

Use the Google Gemini API through Google AI Studio to generate quiz questions.

Keep the AI integration in a separate backend service. Validate the model's response before displaying questions.

Big Pickle is the coding model used by OpenCode. It is NOT the AI model used by the finished application.

- Option A: the AI generates multiple-choice questions ONLY from the
  uploaded text (4 options, 1 correct, short explanation).
- Option B: the AI generates questions from a topic using general knowledge.
- Output is JSON, validated before use. Uploaded text is untrusted content.
- If the AI is wrong or fails: show a friendly error and let the user retry.
  Explanations are shown so learners can spot mistakes.

## 7. Data

Initial prototype: SQLite for storing users, submitted quiz results, and per-question review snapshots.

Plan for PostgreSQL as a later database upgrade.

Never store API keys in source code or commit them to Git.

- users: id, email (unique), password_hash, created_at
- quiz_results: id, user_id, mode, topic, source_name, difficulty,
  question_count, score, percentage, created_at
- quiz_result_items: id, result_id, position, question_text, option_a,
  option_b, option_c, option_d, correct_option, user_option, explanation,
  is_correct, source_snippet
- ai_requests (optional, if time): id, user_id, mode, model, tokens_used,
  created_at
- Active quizzes and temporary uploaded content are held in backend memory
  only and disappear when the backend restarts. The prototype runs as a
  single backend process.
- Submitted quiz results and per-question review snapshots are persisted in
  SQLite so learners can review answers, explanations, and history.
- Temporary uploads are tied to the authenticated user. Ownership is checked
  on every request that uses an upload or quiz id.

## 8. Technology Stack

- Python
- Streamlit for the user interface
- FastAPI for the backend API
- SQLite initially; PostgreSQL later
- Pydantic for data validation
- Google Gemini API (free tier)for quiz generation
- Git and GitHub for version control
- Pytest for testing
- Secure password hashing for user accounts
- Text extraction: PDF, DOCX and TXT
- JWT-based authentication for protected API routes
- Authentication is included in the initial prototype: register, log in, log out, and protected pages/routes.

## 9. Security and Reliability

- Keep API keys in environment variables.
- Never commit `.env` files.
- Logging out clears the JWT from the Streamlit session but does not revoke a
  copied token immediately; a copied token remains valid until it expires.
- Validate uploaded file types and sizes.
- Never execute uploaded files.
- Treat uploaded document text as untrusted learning content, not as instructions to the AI.
- Do not invent answers unsupported by uploaded material.
- Handle invalid files, insufficient content, AI errors, and timeouts with helpful messages.

## 10. Acceptance Checks

The initial prototype should allow a learner to:

1. Open the application.
2. A user can register, log in and log out; pages need login
3. Choose uploaded material or a topic.
4. Valid PDF, DOCX and TXT files are read and previewed
5. Unsupported, empty or unreadable files show a helpful error
6. A topic quiz and an uploaded-content quiz both generate questions
7. Each question has 4 options, 1 correct answer and an explanation
8. Configure difficulty and question count.
9. Generate a quiz.
10. Answer and submit questions.
11. View the score, correct answers, and explanations.
12. Start another quiz.
13. The API key is never in the repo or visible in the app
14. Tests pass and the app is deployed

The project should include a README, SPEC.md, AGENTS.md, dependency list, and tests. It should run locally, use environment variables for secrets, and have no committed API keys.