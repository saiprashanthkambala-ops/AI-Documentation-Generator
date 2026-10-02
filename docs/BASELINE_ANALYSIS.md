# Baseline audit

The repository contained a FastAPI/SQLite upload application with a single-pass Gemini/Gemini generator, destructive schema reset logic, wildcard CORS, and ZIP extraction without traversal or expansion limits. The UI was functional but tightly coupled to Gemini status and did not provide versioning or maintenance workflows.

This audit drove the Gemini migration, non-destructive database initialization, controlled CORS, bounded archive extraction, evidence-oriented analysis, and structured service boundaries implemented in this branch. Historical references should not be used as runtime configuration.
