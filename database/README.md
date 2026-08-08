# Database

This directory contains PostgreSQL-specific bootstrap assets, seed definitions and database documentation.

The FastAPI backend remains the only runtime database-access boundary. Application migrations will be managed through the backend migration tooling. Never store credentials, database dumps or real user data here.
