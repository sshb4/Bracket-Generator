# Bates Brackets

A web app to:
- register/login
- auto-login immediately after signup
- recover account password via email link
- create brackets by pasting one team per line
- auto-size bracket to next power of two
- pick BYE teams when needed
- seed in pasted order or random
- invite collaborators by email
- vote match winners (winner of each match is based on current vote totals)
- see live vote standings on each matchup
- save brackets per user account
- share via code or link
- share a filled bracket copy or an empty bracket copy

## Run locally

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

Open http://127.0.0.1:5000

## Email setup (free API)

This project is wired for Resend as an email provider.

Optional environment variables:

```bash
export RESEND_API_KEY="your_resend_key"
export FROM_EMAIL="Bates Brackets <onboarding@your-domain.com>"
```

If `RESEND_API_KEY` is not set, invites and recovery links are still generated, but email delivery is skipped and links are logged to server output.

## Notes

- Data is stored in `app.db` (SQLite) in the project root.
- Existing databases are migrated automatically on app start.
