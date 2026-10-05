# Project guidance

Read README.md for current scope and startup instructions. Use Chinese for user-facing product copy.
Frontend is Vue 3; backend is Python 3.12, FastAPI, CrewAI 1.15.22 and MySQL. Follow law_backend/AGENTS.md for backend work.
Business skills live in law_backend/src/law_backend/skills. The .agents/skills directory contains CrewAI development guidance.
Keep paid MCP optional, source versions immutable, and citation association separate from model support and legal validity.
Never alter the supplied Desktop skill packs or embed credentials. .env, .local and database data are private runtime state.
Use the dedicated MySQL test database and npm run build for relevant verification. Clearly distinguish local tests with synthetic model responses from live cloud verification.
