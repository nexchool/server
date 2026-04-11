#!/usr/bin/env python
"""
Run database migrations using the same Python that runs this script.
Use this if `flask db upgrade` fails (e.g. "No module named 'flask_cors'" or "No such command 'db'").

From the project root (school-ERP):
    python app/run_migrate.py

Or from the app directory:
    cd app && python run_migrate.py

Make sure dependencies are installed for this Python first:
    python -m pip install -r app/requirements.txt   # from school-ERP
    python -m pip install -r requirements.txt     # from app/
"""
import os
import subprocess
import sys

# Directory that contains the "backend" package (app/)
app_dir = os.path.dirname(os.path.abspath(__file__))
os.chdir(app_dir)

# Use the same Python that is running this script
python = sys.executable
env = os.environ.copy()
env["FLASK_APP"] = "app:create_app"
env["PYTHONPATH"] = app_dir

print(f"Using Python: {python}")
print(f"Working dir: {app_dir}")
print("Running: flask db upgrade")
print()

result = subprocess.run(
    [python, "-m", "flask", "db", "upgrade"],
    cwd=app_dir,
    env=env,
)
sys.exit(result.returncode)
