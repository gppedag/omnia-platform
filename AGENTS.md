# Omnia Development Rules

## Repository
- Source of truth: GitHub private repository gppedag/omnia-platform
- Stable branch: main
- Integration branch: develop
- Feature branches: feature/*
- Fix branches: fix/*

## Environment
- Production path: /srv/apps/demo-cup
- Development path: /srv/apps/omnia-dev

## Safety
- NEVER modify /srv/apps/demo-cup directly.
- NEVER modify production .env files.
- NEVER delete Docker volumes.
- NEVER run docker compose down -v.
- NEVER deploy automatically to production.
- NEVER commit secrets, passwords, tokens, private keys or runtime data.

## Git workflow
- Never commit directly to main.
- Prefer a dedicated feature/* or fix/* branch.
- Before committing:
  - run git status
  - inspect git diff
  - run syntax/tests relevant to changed files
- Push work to GitHub.
- Merge to develop/main only after review.

## Minimum checks
Frontend JavaScript:
- node --check frontend/js/app.js

Backend Python:
- compile/check changed Python files
- run available application tests if present

Docker:
- validate compose configuration before starting services.

## Runtime
Development Docker resources must use DEV-specific:
- container names
- networks
- volumes
- ports
- database

Do not reuse production PostgreSQL volumes or upload volumes.

## External integrations
MikoPBX, Chatwoot, LiveKit, vLLM, LiteLLM and other platform services are external dependencies.
Do not modify their production configuration unless explicitly requested.

## Deployment
Development changes must follow:

feature/fix branch
-> test
-> push
-> review
-> develop
-> staging
-> main
-> controlled production deploy
