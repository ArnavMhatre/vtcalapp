# VT Timetable → Google Calendar

This repository contains a FastAPI application that accepts an image of a Virginia Tech timetable, extracts class information using OCR, and creates recurring events in Google Calendar.

## Project structure
- The web UI is provided by `index.html` (served from the project root).
- The application server is implemented in `main.py`.
- The `pyvt` library is included as a submodule at `vendor/pyvt` (fork with local modifications).

## Local checklist
- Place `credentials.json` (Google OAuth client secret) in the project root. Do not commit this file.
- Run the application locally and complete the OAuth flow to generate `token.pickle`. Do not commit the token file.
- Install the `pyvt` submodule in editable mode so the application can import it as `pyvt`.

## Setup (Windows, bash)
From the project root (`C:/Users/arnav/vscode/calapp`) execute:

1) Create and activate a virtual environment, then install dependencies:

```bash
python -m venv venv
source venv/Scripts/activate   # Windows bash
python -m pip install -r requirements.txt
```

2) Initialize and fetch submodules (when cloning):

```bash
git submodule update --init --recursive
```

3) Install the `pyvt` submodule in editable mode (recommended):

```bash
python -m pip install -e vendor/pyvt
```

This allows the application to import the library as:

```py
from pyvt import Timetable
```

4) Start the application:

```bash
py main.py
# or
python main.py
```

Open http://localhost:8000 in a browser to use the web UI.

## Environment and credentials
1. Go to the Google Cloud Console: https://console.cloud.google.com/.
2. Create a new project or select an existing project.
3. Navigate to "APIs & Services" → "Credentials".
4. Click "Create Credentials" and select "OAuth client ID".
5. Configure the consent screen and download the json file and rename it as credentials.json

## Working with the `pyvt` fork
- The fork is included as a submodule at `vendor/pyvt`.
- To apply local changes in the fork: edit files inside `vendor/pyvt`, then run `cd vendor/pyvt` and use normal git commands (`git add`, `git commit`, `git push`) to update the fork.
- To update the submodule pointer in this repository after pushing changes to the fork:

```bash
git submodule update --remote vendor/pyvt
git add vendor/pyvt
git commit -m "Update pyvt submodule"
git push
```

## Security
- Do not commit `credentials.json` or `token.pickle`. If credentials are accidentally pushed, rotate/revoke them immediately and remove them from Git history.

## Troubleshooting
- If event times appear shifted, confirm that the system timezone and the configured Google Calendar timezone (`America/New_York`) are handled correctly. The code uses `pytz` for timezone localization.
- OCR requires Tesseract to be installed on the host system and available on the PATH.

## License and attribution
The project is released under the MIT License — see the `LICENSE` file in this repository for details.  
Third‑party code: the `pyvt` code included as a submodule at `vendor/pyvt` is maintained under its original license; retain attribution and any license files inside `vendor/pyvt`.
