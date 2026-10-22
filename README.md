# ClassLens AI

ClassLens AI is a Streamlit app that uploads a class video for a structured Google Gemini review across five teaching-quality dimensions. The app requires the user to provide a Gemini API key and confirm organizer approval before sending the recording.

## Setup

1. Create and activate a virtual environment.
2. Install dependencies:
   ```powershell
   python -m pip install -r requirements.txt
   ```
3. Run the app:
   ```powershell
   streamlit run app.py
   ```
4. Get a Gemini API key from [Google AI Studio](https://aistudio.google.com/apikey), enter it in the app, upload a supported video, and confirm authorization.

For local use, organizer approval can be enabled in PowerShell after approval:

```powershell
$env:GEMINI_PROVIDER_APPROVED = "true"
streamlit run app.py
```

On Streamlit Community Cloud, set `GEMINI_PROVIDER_APPROVED=true` in the app's environment/secrets after approval. Users can enter their own key in the password-masked field. Alternatively, store a key as `GEMINI_API_KEY` in trusted deployment secrets. Do not commit keys to the repository.

Check Google's current [pricing](https://ai.google.dev/gemini-api/docs/pricing), [terms](https://ai.google.dev/gemini-api/terms), availability, quota, and data-use rules. A free tier may be available, but it is not guaranteed. Organizer approval and participant permissions must be in place before any recording is uploaded to Google.

## Deploy on Streamlit Community Cloud

1. Push this project to a GitHub repository.
2. In [Streamlit Community Cloud](https://share.streamlit.io/), choose **Create app** and select the repository, branch, and `app.py` as the main file.
3. In the app's **Settings → Secrets**, add `GEMINI_PROVIDER_APPROVED = "true"` only after organizer approval. Users can enter their own Gemini API key in the app. If using a shared deployment key instead, add `GEMINI_API_KEY = "your-key"` as a secret; never add it to this repository.
4. Save the secrets and redeploy the app.

## Features

- Upload video files up to 250 MB (MP4, MOV, AVI, MKV, WebM).
- Upload one video at a time; choosing another video clears the previous assessment.
- Direct Gemini analysis of video and embedded audio.
- Structured assessment with rubric scores, evidence, strengths, improvements, and limitations.
- Communication-language identification with a confidence estimate.
- Evidence-weighted overall score mapped to explicit Poor, Average, Good, and Excellent rating bands.
- Downloadable JSON and styled PDF assessments.
- Segmented blue score bars showing dimension ratings at a glance.
- Upload and video-processing progress messages, with explicit timeout and provider errors.
- Temporary provider upload is deleted after processing; cleanup failures are reported.

## Privacy and limitations

- The video and its audio are sent to Google Gemini for analysis.
- User-entered API keys are used for the request and are not included in the downloaded report.
- Local temporary media files are removed after assessment.
- Generated scores and evidence can be wrong; verify claims against the recording before relying on or sharing the report.
- The assessment has not been validated against labeled recordings and is not a validated measure of teaching quality.
- Student names and other personal information may appear in the generated report. Remove identifying details before public sharing, especially for minors.

## Testing

Run the test suite from the project root:

```powershell
python -m pytest -q
```
