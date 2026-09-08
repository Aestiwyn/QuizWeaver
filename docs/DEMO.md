# TeachFlow Demo

This is the current, Windows-verified demo guide. It uses only fictional
content and the Mock provider; it never needs an API key.

## Prepare an isolated demo copy

Do not reset a working teacher database. Copy the project to a new empty
folder, then open PowerShell in that copy:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Create `config.yaml` from `config.yaml.example`, set `llm.provider: mock`, and
use an isolated database path such as `demo_data/teachflow_demo.db`. Do not
copy `.env`, `.venv`, `quiz_warehouse.db`, `uploads`, or personal settings from
another installation.

To recreate fictional demo data in Git Bash or WSL, from the project root:

```bash
bash scripts/reset_demo.sh
```

The script operates on `demo_data/teachflow_demo.db` by default and refuses to
reset `quiz_warehouse.db`. Set `TEACHFLOW_DEMO_DB` only to another isolated demo
path when needed. It is not a maintenance or recovery tool for a working DB.

## Start the application

On Windows, run `run.bat` from the project root. For a manual local start:

```powershell
.\.venv\Scripts\python.exe -c "import yaml; from src.web.app import create_app; config=yaml.safe_load(open('config.yaml', encoding='utf-8')); create_app(config).run(host='127.0.0.1', port=5000)"
```

Open `http://127.0.0.1:5000`, create the local demo administrator account, and
keep the terminal open. Mock mode makes no network model calls.

## Five-minute demonstration route

1. Create or select the fictional class **七年级科学 A 班**.
2. Open **记录课程** and either upload a fictional, text-based PDF/DOCX or enter
   the example topic `光合作用、细胞能量` and a short invented lesson summary.
3. From that class, select **生成测验**. Choose the recorded lesson (or current
   input), leave the provider on **Mock**, and generate five questions.
4. On the quiz detail page, expand **本测验的生成依据** and point out the content
   source, generator/Critic status, and mock cost.
5. Edit a question if needed, then use **确认测验可用**. This is the teacher
   review step; generation alone does not publish a quiz.
6. Use the export controls to download a teacher copy and a student copy, and
   explain that the student copy omits answers.

## Verification notes

Run `python -m pytest -p no:cacheprovider -q` for the current test result; do
not quote a fixed test count here. Historical workshop scripts and statistics
are retained only as historical material and are not setup instructions.

## Historical material

Earlier workshop-era commands, screenshots, counts, and paths may be useful as
project history, but are not a guide to the current application. In particular,
there is no root `app.py` launch command and the reset script is
`scripts/reset_demo.sh`.
