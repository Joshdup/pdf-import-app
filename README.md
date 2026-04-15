# PDF/Image Statement Uploader

A small Flask app for uploading multiple PDF and image files and extracting text in one place.

## Setup

1. Install dependencies:
   ```bash
   python -m pip install -r requirements.txt
   ```

2. Run the app:
   ```bash
   python app.py
   ```

3. Open the browser at `http://127.0.0.1:5000`

## Notes

- Place your files in the upload form and choose multiple files.
- The app supports `.pdf`, `.png`, `.jpg`, `.jpeg`, `.tif`, and `.tiff`.
- The app parses transaction rows and generates an Excel report with transaction and summary sheets.
- Update `pytesseract.pytesseract.tesseract_cmd` in `app.py` if needed.

## Hosting

### Local hosting

1. Install dependencies:
   ```bash
   python -m pip install --user -r requirements.txt
   ```
2. Run the app:
   ```bash
   python app.py
   ```
3. Visit `http://127.0.0.1:5000`

### Deploy to Render

1. Push this project to a Git repository (GitHub, GitLab, or Bitbucket).
2. Create a new Web Service on Render and connect your repository.
3. Render will use `render.yaml` and `Procfile` to build and start the app.
4. If the build succeeds, the app will launch automatically.

#### Important

- Render must have the Tesseract binary installed. If the managed image does not include it, use a custom Docker deployment or install Tesseract using a startup script.
- Keep `pytesseract.pytesseract.tesseract_cmd` updated if the binary path differs on the host.

### General deploy notes

- Use `gunicorn app:app --bind 0.0.0.0:$PORT` for the web process.
- The app is configured to listen on `0.0.0.0` and use the `PORT` environment variable when available.
