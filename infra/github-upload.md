# Upload to GitHub

This workspace is not currently a Git repository and the `gh` CLI is not installed here.

If you already have a GitHub repo, run this from the workspace root:

```bash
git init
git add python-marketmate infra
git commit -m "Add Python MarketMate app with OpenTelemetry and EC2 deployment"
git branch -M main
git remote add origin https://github.com/YOUR_USER/YOUR_REPO.git
git push -u origin main
```

If your repo is private, the EC2 instance will need a private deploy method. The simplest demo path is a public repo with no secrets committed. Do not commit `OPENAI_API_KEY`.

