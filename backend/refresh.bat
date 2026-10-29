@echo off
cd /d %~dp0
call .venv\Scripts\activate
python prices.py
python announcements.py
python enrich.py
git add data
git commit -m "Data refresh"
git push
echo Done. Render redeploys in about 3 minutes.
