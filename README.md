# Preference elicitation pilot — Render and Prolific

Adapted from the supplied lottery experiment and deployed Ring Game server.
The experimental choices, repetitions, randomization, instructions and payment
rules are retained. This is a separate project: do not overwrite the Ring Game repository.

## 1. Upload to GitHub
Create a new repository, e.g. preference-elicitation-pilot. Upload index.html,
server.py and render.yaml at the repository root (not inside another folder).
README.md and .gitignore can also be included. No requirements.txt is needed:
the server uses Python's standard library.

## 2. Deploy on Render
Use New > Blueprint, select the new repository, and use render.yaml.
The supplied YAML retains the paid plan identifier from your previous deployment.
Review the price shown by Render before creating the service. If that plan is
unavailable, choose a current paid instance supporting a persistent disk.

Enter SUCCESS_CODE and SCREENOUT_CODE from the NEW Prolific study. Do not reuse
the Ring Game codes. Enter only each code, not the full completion URL.
Configure the screen-out code's action and payment in Prolific for this study.
The HTML does not specify a screen-out payment amount; confirm that arrangement
and the consent wording before recruitment.

Manual alternative: New > Web Service; Python runtime; build command empty
(or `python -m py_compile server.py` if a command is required); start command
`python server.py`; health check `/healthz`; choose a paid instance. Add a 1 GB
persistent disk at `/var/data`, DATA_DIR=/var/data, a long random ADMIN_TOKEN,
and SUCCESS_CODE and SCREENOUT_CODE. Keep ADMIN_TOKEN private.

## 3. Preview before opening recruitment
Open https://YOUR-SITE.onrender.com/?preview=1&PROLIFIC_PID=TEST001&STUDY_ID=TEST&SESSION_ID=TEST001
Preview runs are saved with the supplied test IDs, but do not redirect to Prolific.
Exclude test IDs from analysis. Each page load creates a separate random run ID;
refreshing starts a new run, and does not resume previous progress.

Complete one full run (150 decisions: 45 pairwise, 45 BDM, 60 instructed), then
check the exports. Also test declining consent and failing a comprehension check
twice. Test temporary connection loss and retry at the final save screen.
After setting the codes, use Prolific's own Preview to check both return paths.
The app blocks non-preview entry if either code or the three Prolific IDs is missing.

## 4. Prolific
Use the Render base URL as the Study URL and select URL parameters for participant
identification. Verify PROLIFIC_PID, STUDY_ID and SESSION_ID appear in the final
URL. Use desktop/laptop eligibility because the task uses the space bar.
The current task promises an £8 base payment and a 10% bonus draw; match the study
setup to those instructions. Only bonus-draw winners receive the £5 endowment.

## 5. Download data
https://YOUR-SITE.onrender.com/researcher?token=YOUR_ADMIN_TOKEN

The dashboard provides summary CSV, trial CSV and raw JSON downloads.
- `bonus_amount`: lottery result plus any BDM transfer, excluding endowment.
- `endowment`: £5 for bonus-draw winners, otherwise £0.
- `total_bonus`: actual additional payment, including endowment; excludes base pay.
- `prolific_pid`, `study_id`, `session_id`: Prolific identifiers.
- `participant_id`: unique run ID, so repeat runs are retained separately.
- `response`: original numeric response; pairwise/instructed 0=left, 1=right.
- `response_label`: Lottery 1 / Lottery 2 for pairwise/instructed responses.
- `ref_side`: where the reference lottery was displayed.
- `status`: in_progress, screened_out or complete.
The raw JSON also contains all jsPsych trial records and the original-style CSV.
Never distribute the admin URL to participants or commit the database to GitHub.

## Saving behavior
No research data are saved before consent or after declining consent. After
consent, full snapshots are queued in order after each trial. Temporary failures
are recovered by later snapshots; final saving has a retry button. Completion
requires a successful final save and a verification read, including 150 valid
decisions for a complete run. Late in-progress saves cannot overwrite final status.
Closing the tab before a save finishes can lose the latest responses; there is no
resume feature. The server does not independently recompute the browser's bonus
lottery. This retains the supplied pilot's browser-side payment calculation.

## Local run
ADMIN_TOKEN=test-secret DATA_DIR=./data python3 server.py
Open http://127.0.0.1:8000/?preview=1&PROLIFIC_PID=TEST001

## Validation performed
Python compilation; JavaScript execution with a simulated jsPsych data layer;
HTTP/SQLite integration for 150-decision completion, screen-out, consent decline,
failed-save retry, export authorization and total-bonus arithmetic. The external
jsPsych CDN and browser rendering could not be tested in the build environment.
A full hosted browser preview is therefore required before recruiting.
