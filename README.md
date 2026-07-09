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
4. Once deployed, open the Render URL and share it with your friend.

### Important DB note

- This app currently uses SQLite (`app.db`).
- On free cloud instances, local disk may reset after restarts/redeploys.
- For durable hosted data, move to managed Postgres (I can wire this next).
