# Bracket Maker

A super simple web app to:
- register/login
- create brackets by pasting one team per line
- auto-size bracket to next power of two
- pick BYE teams when needed
- seed in pasted order or random
- click winners to advance rounds
- save brackets per user account
- share a bracket via link so another user can add a copy to their account

## Run locally

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

Open http://127.0.0.1:5000

## Notes

- Data is stored in `app.db` (SQLite) in the project root.
- Sharing currently creates a copy in the recipient's account.

## Deploy and share (Render)

1. Go to Render and connect your GitHub account.
2. Create a new Blueprint service and pick this repo.
3. Render will detect `render.yaml` and create the web app.
4. In Neon (free tier), create a Postgres project and copy the connection string.
5. In Render service settings, add env var `DATABASE_URL` with your Neon connection string.
6. Redeploy, then open the Render URL and share it with your friend.

### Database behavior

- Local development uses SQLite (`app.db`) when `DATABASE_URL` is not set.
- Hosted deployment should use Postgres via `DATABASE_URL` for durable data.
