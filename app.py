from __future__ import annotations

import hashlib
import html
import json
import os
import tempfile
from pathlib import Path

import streamlit as st
from streamlit.errors import StreamlitSecretNotFoundError

from classlens.assessment import AssessmentError
from classlens.config import DEFAULT_RUBRIC, gemini_permission_error, validate_uploaded_file
from classlens.gemini_assessment import assess_video_with_gemini
from classlens.report_pdf import build_assessment_pdf

VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".webm"}


st.set_page_config(page_title="ClassLens AI", page_icon="🎓", layout="wide")

st.markdown(
    """
    <style>
    :root {
        --lens-ink: var(--text-color);
        --lens-muted: color-mix(in srgb, var(--text-color) 68%, transparent);
        --lens-line: color-mix(in srgb, var(--text-color) 18%, var(--background-color));
        --lens-surface: var(--secondary-background-color);
        --lens-page-top: var(--background-color);
        --lens-page-bottom: var(--background-color);
        --lens-control-bg: var(--secondary-background-color);
        --lens-control-border: color-mix(in srgb, var(--text-color) 22%, var(--secondary-background-color));
        --lens-upload-border: color-mix(in srgb, var(--primary-color) 58%, var(--secondary-background-color));
        --lens-upload-start: color-mix(in srgb, var(--primary-color) 10%, var(--secondary-background-color));
        --lens-upload-end: var(--secondary-background-color);
        --lens-card: var(--secondary-background-color);
        --lens-report-border: color-mix(in srgb, var(--primary-color) 30%, var(--secondary-background-color));
        --lens-report-start: var(--secondary-background-color);
        --lens-report-mid: color-mix(in srgb, var(--primary-color) 7%, var(--secondary-background-color));
        --lens-report-end: color-mix(in srgb, var(--primary-color) 12%, var(--secondary-background-color));
        --lens-report-summary: color-mix(in srgb, var(--text-color) 82%, transparent);
        --lens-accent: var(--primary-color);
        --lens-download: var(--primary-color);
        --lens-pill-border: color-mix(in srgb, var(--primary-color) 35%, var(--secondary-background-color));
        --lens-pill-bg: color-mix(in srgb, var(--primary-color) 9%, var(--secondary-background-color));
        --lens-score-track: color-mix(in srgb, var(--text-color) 12%, var(--secondary-background-color));
    }
    .stApp, [data-testid="stAppViewContainer"], [data-testid="stMain"] {
        color: var(--text-color) !important;
        background:
            radial-gradient(ellipse at 92% 0%, rgba(105, 177, 255, .13), transparent 32rem),
            linear-gradient(180deg, var(--lens-page-top) 0%, var(--lens-page-bottom) 100%) !important;
    }
    header[data-testid="stHeader"] { background:transparent !important; }
    [data-testid="stSidebar"] { background:var(--secondary-background-color) !important; }
    .stApp [data-testid="stMarkdownContainer"],
    .stApp [data-testid="stCaptionContainer"],
    .stApp label,
    .stApp [data-testid="stWidgetLabel"],
    .stApp [data-testid="stWidgetLabel"] *,
    .stApp [data-testid="stCaptionContainer"] * { color: var(--text-color) !important; }
    .block-container { max-width: 1120px; padding-top: 3.2rem; padding-bottom: 4rem; }
    h1, h2, h3 { color: var(--lens-ink); letter-spacing: -.025em; }
    h2 { margin-top: 1.6rem; }
    .lens-brand { display:flex; align-items:center; gap:14px; margin: 0 0 1rem; }
    .lens-brand-icon {
        display:flex; align-items:center; justify-content:center; width:48px; height:48px;
        border-radius:16px; color:#fff; font-size:24px;
        background:linear-gradient(140deg,#58c4ff,#2577f4 58%,#5147db);
        box-shadow:0 10px 24px rgba(37,119,244,.24);
    }
    .lens-brand-title { color:var(--lens-ink); font-size:1.8rem; line-height:1.1; font-weight:760; letter-spacing:-.045em; }
    .lens-brand-subtitle { margin-top:5px; color:var(--lens-muted); font-size:.92rem; }
    .lens-eyebrow { color:var(--lens-accent); font-size:.72rem; font-weight:750; letter-spacing:.13em; text-transform:uppercase; }
    .lens-upload-heading { color:var(--lens-ink); font-size:1.15rem; font-weight:700; letter-spacing:-.02em; margin-bottom:.2rem; }
    .lens-upload-copy { color:var(--lens-muted); font-size:.9rem; margin-bottom:.8rem; }
    div[data-testid="stFileUploader"] {
        padding: 1rem; border:1px dashed var(--lens-upload-border); border-radius:16px;
        background:linear-gradient(140deg,var(--lens-upload-start),var(--lens-upload-end));
    }
    div[data-testid="stFileUploader"] section { border:0; background:transparent; }
    div[data-testid="stTextInput"] input {
        border-radius:12px; border-color:var(--lens-control-border); background:var(--lens-control-bg); color:var(--lens-ink);
    }
    div[data-testid="stTextInput"] input::placeholder { color:var(--lens-muted); }
    div[data-testid="stExpander"] details { border-color:var(--lens-line); background:var(--lens-surface); }
    div[data-testid="stAlert"] { background:var(--lens-surface); }
    div[data-testid="stButton"] button[kind="primary"] {
        border:0; border-radius:12px; min-height:48px; padding:0 1.4rem;
        background:linear-gradient(100deg,#1686ff,#475be9);
        box-shadow:0 8px 20px rgba(37,119,244,.2); font-weight:700;
        transition:transform .16s ease, box-shadow .16s ease;
    }
    div[data-testid="stButton"] button[kind="primary"]:hover {
        transform:translateY(-1px); box-shadow:0 11px 24px rgba(37,119,244,.28);
    }
    div[data-testid="stDownloadButton"] button {
        border:1px solid var(--lens-control-border); border-radius:11px; min-height:44px;
        background:var(--lens-control-bg); color:var(--lens-download); font-weight:650;
    }
    div[data-testid="stMetric"] {
        padding:1rem 1.1rem; border:1px solid var(--lens-line); border-radius:16px;
        background:var(--lens-card); box-shadow:0 5px 16px rgba(16,42,67,.08);
    }
    div[data-testid="stMetricLabel"] { color:var(--lens-muted); font-size:.78rem; }
    div[data-testid="stMetricValue"] { color:var(--lens-ink); font-weight:740; }
    .lens-report-hero {
        display:flex; align-items:center; justify-content:space-between; gap:20px;
        padding:1.35rem 1.5rem; margin:.4rem 0 1rem;
        border:1px solid var(--lens-report-border); border-radius:20px;
        background:linear-gradient(115deg,var(--lens-report-start) 0%,var(--lens-report-mid) 62%,var(--lens-report-end) 100%);
        box-shadow:0 12px 32px rgba(19,70,130,.065);
    }
    .lens-report-label { color:var(--lens-accent); font-size:.72rem; font-weight:750; letter-spacing:.12em; text-transform:uppercase; }
    .lens-report-rating { color:var(--lens-ink); font-size:2.15rem; font-weight:780; letter-spacing:-.05em; line-height:1.15; margin:.25rem 0; }
    .lens-report-summary { color:var(--lens-report-summary); font-size:.94rem; line-height:1.55; max-width:720px; }
    .lens-report-score {
        display:flex; flex:0 0 92px; width:92px; height:92px; align-items:center; justify-content:center;
        border:5px solid #77baff; border-right-color:#4359e8; border-radius:50%;
        color:var(--lens-download); background:var(--lens-control-bg); font-size:1.12rem; font-weight:760;
        box-shadow:0 5px 17px rgba(37,119,244,.14);
    }
    .lens-section-label {
        display:flex; align-items:center; gap:9px; margin:1.55rem 0 .6rem;
        color:var(--lens-ink); font-size:1.18rem; font-weight:730; letter-spacing:-.025em;
    }
    .lens-section-dot { display:inline-block; width:8px; height:8px; border-radius:50%; background:#368cff; box-shadow:0 0 0 4px #e3f0ff; }
    .lens-pill {
        display:inline-flex; align-items:center; padding:5px 11px; border-radius:999px;
        border:1px solid var(--lens-pill-border); color:var(--lens-download); background:var(--lens-pill-bg); font-size:.8rem; font-weight:650;
    }
    @media (max-width: 700px) {
        .block-container { padding:2rem 1rem 3rem; }
        .lens-report-hero { align-items:flex-start; padding:1.05rem; }
        .lens-report-rating { font-size:1.75rem; }
        .lens-report-score { flex-basis:72px; width:72px; height:72px; font-size:.98rem; }
    }
    </style>
    """,
    unsafe_allow_html=True,
)


def _get_app_setting(name: str) -> str:
    value = os.getenv(name, "")
    if value:
        return value
    try:
        return str(st.secrets.get(name, ""))
    except StreamlitSecretNotFoundError:
        return ""


def _score_badge(score: int) -> str:
    return f"{score}/5"


def _render_dimensions(dimensions):
    score_labels = {
        1: "Limited evidence",
        2: "Emerging evidence",
        3: "Developing",
        4: "Strong evidence",
        5: "Consistently strong",
    }
    st.markdown(
        """
        <style>
        .classlens-score-track { display:flex; gap:5px; margin:6px 0 14px; }
        .classlens-score-segment { height:12px; flex:1; border-radius:8px; background:var(--lens-score-track); }
        .classlens-score-segment.filled { background:linear-gradient(100deg,#67c8ff 0%,#2188ff 58%,#3155e7 100%); box-shadow:0 2px 8px rgba(33,136,255,.28); }
        .classlens-score-label { display:flex; align-items:center; justify-content:space-between; gap:12px; }
        .classlens-score-pill { border:1px solid var(--lens-pill-border); border-radius:999px; padding:3px 10px; color:var(--lens-download); background:var(--lens-pill-bg); font-weight:700; font-size:.82rem; }
        .classlens-score-hint { color:var(--lens-muted); font-size:.82rem; }
        </style>
        """,
        unsafe_allow_html=True,
    )
    st.caption("Dimension score scale: 1 = limited evidence; 5 = consistently strong evidence.")
    for dimension in dimensions:
        name = dimension["name"]
        score = dimension["score"]
        st.markdown(
            f"### {name} — {_score_badge(score)}"
        )
        st.write(dimension["evidence"])
        st.caption(f"Limitation: {dimension['limitation']}")
        segments = "".join(
            f"<span class='classlens-score-segment{' filled' if index < score else ''}'></span>"
            for index in range(5)
        )
        st.markdown(
            f"<div class='classlens-score-label'>"
            f"<span class='classlens-score-hint'>{score_labels[score]}</span>"
            f"<span class='classlens-score-pill'>{score}/5</span>"
            f"</div><div class='classlens-score-track' role='img' "
            f"aria-label='Score {score} out of 5'>{segments}</div>",
            unsafe_allow_html=True,
        )


def _render_rubric_legend():
    with st.expander("How the score was determined"):
        st.markdown(
            """
            Gemini reviews the uploaded video and its embedded audio directly against the rubric dimensions.
            Dimension scores are combined using the displayed rubric weights. The weighted result maps to Poor (<2.5), Average (2.5 to <3.5), Good (3.5 to <4.5), or Excellent (4.5 to 5).
            Confidence reflects evidence coverage and technical limitations; it does not guarantee correctness.
            """
        )
        for name, weight in DEFAULT_RUBRIC.items():
            st.write(f"- {name}: {weight * 100:.0f}%")


def _render_section_heading(title: str) -> None:
    st.markdown(
        f"<div class='lens-section-label'><span class='lens-section-dot'></span>{html.escape(title)}</div>",
        unsafe_allow_html=True,
    )


def _process_gemini_video(
    uploaded_file,
    user_confirmed_provider_use: bool,
    api_key: str | None,
    on_progress=None,
):
    if uploaded_file is None:
        raise ValueError("A video recording must be uploaded first.")
    approval_error = gemini_permission_error(
        user_confirmed_provider_use,
        provider_approved=_get_app_setting("GEMINI_PROVIDER_APPROVED"),
    )
    if approval_error:
        raise AssessmentError(approval_error)
    if not api_key:
        raise AssessmentError(
            "Enter a Gemini API key or configure GEMINI_API_KEY in the app's environment/secrets."
        )

    valid, message = validate_uploaded_file(uploaded_file)
    if not valid:
        raise ValueError(message)
    extension = Path(uploaded_file.name).suffix.lower()
    if extension not in VIDEO_EXTENSIONS:
        raise ValueError("Google Gemini video review requires a video file.")

    with tempfile.TemporaryDirectory(prefix="classlens_gemini_") as work_dir:
        video_path = os.path.join(work_dir, Path(uploaded_file.name).name)
        with open(video_path, "wb") as sink:
            sink.write(uploaded_file.getvalue())
        report = assess_video_with_gemini(
            video_path,
            api_key=api_key,
            model=_get_app_setting("GEMINI_MODEL") or "gemini-3.8-flash",
            on_progress=on_progress,
        )
    report.update({
        "filename": uploaded_file.name,
        "filesize_bytes": uploaded_file.size,
    })
    return report


st.markdown(
    """
    <div class="lens-brand">
        <div class="lens-brand-icon">C</div>
        <div>
            <div class="lens-brand-title">ClassLens</div>
            <div class="lens-brand-subtitle">A clearer view of every classroom</div>
        </div>
    </div>
    <div class="lens-eyebrow">Video-based teaching review</div>
    """,
    unsafe_allow_html=True,
)

st.markdown("## Turn a class recording into useful feedback")
st.markdown(
    "<p style='color:var(--lens-muted);margin-top:-.7rem;margin-bottom:1.4rem'>"
    "Upload one lesson video to receive a structured review of teaching evidence, "
    "communication language, strengths, and opportunities to improve.</p>",
    unsafe_allow_html=True,
)

_render_section_heading("Your recording")
upload_col, key_col = st.columns([1.15, 0.85], gap="large")
with upload_col:
    st.markdown(
        "<div class='lens-upload-heading'>Upload a class video</div>"
        "<div class='lens-upload-copy'>One file per review · MP4, MOV, AVI, MKV, or WebM</div>",
        unsafe_allow_html=True,
    )
    uploaded_file = st.file_uploader(
        "Choose a video",
        type=[ext.lstrip(".") for ext in sorted(VIDEO_EXTENSIONS)],
        accept_multiple_files=False,
        label_visibility="collapsed",
    )
with key_col:
    st.markdown(
        "<div class='lens-upload-heading'>Connect Gemini</div>"
        "<div class='lens-upload-copy'>Your key is used to request this review.</div>",
        unsafe_allow_html=True,
    )
    gemini_api_key = st.text_input(
        "Gemini API key",
        value=_get_app_setting("GEMINI_API_KEY"),
        type="password",
        help="Get a key from Google AI Studio. A free tier may be available depending on region and current limits.",
    )
    st.markdown(
        f"<span class='lens-pill'>{'Provider approved' if _get_app_setting('GEMINI_PROVIDER_APPROVED').lower() == 'true' else 'Approval setup required'}</span>",
        unsafe_allow_html=True,
    )

approval_status = (
    "Organizer approval: configured."
    if _get_app_setting("GEMINI_PROVIDER_APPROVED").lower() == "true"
    else "Organizer approval: not configured. Set GEMINI_PROVIDER_APPROVED=true in the app environment after approval."
)
if _get_app_setting("GEMINI_PROVIDER_APPROVED").lower() != "true":
    st.warning(approval_status)

if uploaded_file is not None:
    st.markdown(
        f"<div class='lens-pill'>Ready to review · {html.escape(uploaded_file.name)} · "
        f"{uploaded_file.size / (1024 * 1024):.1f} MB</div>",
        unsafe_allow_html=True,
    )
    with st.expander("Preview uploaded video", expanded=False):
        st.video(uploaded_file.getvalue())

upload_token = (
    hashlib.sha256(uploaded_file.getvalue()).hexdigest()[:16]
    if uploaded_file is not None
    else None
)
if st.session_state.get("_active_upload_token") != upload_token:
    st.session_state.pop("last_report", None)
    st.session_state.pop("_report_upload_token", None)
    st.session_state["_active_upload_token"] = upload_token

provider_approval_confirmed = st.checkbox(
    "I confirm the organizer has approved Google Gemini for this recording and I am authorized to send it there.",
    key=f"cloud_permission_Google Gemini_{upload_token}",
    help="This confirmation is not a substitute for organizer approval. Analysis remains disabled unless the app administrator has configured GEMINI_PROVIDER_APPROVED=true.",
)
with st.expander("Privacy and consent", expanded=False):
    st.markdown(
        "The video and embedded audio will be sent to Google Gemini. Continue only if the organizer has approved this provider and any required participant permissions are in place. The temporary Google upload is deleted after review."
    )

action_col, note_col = st.columns([0.38, 0.62])
with action_col:
    analyze_clicked = st.button("Generate class review", type="primary", use_container_width=True)
with note_col:
    st.caption("Usually a few minutes · You can export the finished review as PDF or JSON")

if analyze_clicked:
    if uploaded_file is None:
        st.error("Please upload a class video first.")
    else:
        try:
            with st.spinner("Processing video and evaluating teaching quality..."):
                progress_message = st.empty()
                report = _process_gemini_video(
                    uploaded_file,
                    provider_approval_confirmed,
                    gemini_api_key,
                    on_progress=progress_message.info,
                )
            st.session_state["last_report"] = report
            st.session_state["_report_upload_token"] = upload_token
        except (ValueError, AssessmentError) as exc:
            st.error(str(exc))
            st.stop()

if (
    "last_report" in st.session_state
    and (
        "_report_upload_token" not in st.session_state
        or st.session_state["_report_upload_token"] != upload_token
    )
):
    st.session_state.pop("last_report")
    st.session_state.pop("_report_upload_token", None)

if "last_report" in st.session_state:
    report = st.session_state["last_report"]
    summary = report["summary"]
    rating = report["rating"]
    confidence = report["confidence"]
    st.markdown(
        f"<div class='lens-report-hero'>"
        f"<div><div class='lens-report-label'>Your class review · {html.escape(confidence)} confidence</div>"
        f"<div class='lens-report-rating'>{html.escape(rating)}</div>"
        f"<div class='lens-report-summary'>{html.escape(summary)}</div>"
        f"<div style='margin-top:12px'><span class='lens-pill'>"
        f"Communication: {html.escape(report['communication_language'])} "
        f"· {html.escape(report['language_confidence'])} confidence</span></div></div>"
        f"<div class='lens-report-score'>{report['overall_score']:.2f}<span style='font-size:.7rem'>/5</span></div>"
        f"</div>",
        unsafe_allow_html=True,
    )

    top_columns = st.columns(4)
    with top_columns[0]:
        st.metric("Overall rating", rating)
    with top_columns[1]:
        st.metric("Weighted rubric score", f"{report['overall_score']}/5")
    with top_columns[2]:
        st.metric("Confidence", confidence)
    with top_columns[3]:
        st.metric("Video analysis", "Direct")

    _render_section_heading("Overall assessment")
    st.write(summary)

    _render_section_heading("Teaching dimensions")
    _render_dimensions(report["dimensions"])

    _render_section_heading("What worked well")
    for item in report["strengths"]:
        st.markdown(f"- {item}")

    _render_section_heading("Opportunities to improve")
    for item in report["improvements"]:
        st.markdown(f"- {item}")

    _render_section_heading("Technical notes and limitations")
    for item in report["limitations"]:
        st.markdown(f"- {item}")

    with st.expander("Analysis details"):
        st.write("Video and embedded audio analyzed directly by Google Gemini.")
        st.caption(report["frame_summary"])
        for note in report["analysis_notes"]:
            st.caption(note)

    _render_rubric_legend()

    json_payload = json.dumps(report, indent=2)
    pdf_payload = build_assessment_pdf(report)
    pdf_col, json_col, _ = st.columns([0.28, 0.28, 0.44])
    with pdf_col:
        st.download_button(
            label="Download PDF",
            data=pdf_payload,
            file_name="classlens_class_review.pdf",
            mime="application/pdf",
            use_container_width=True,
        )
    with json_col:
        st.download_button(
            label="Download JSON",
            data=json_payload,
            file_name="classlens_gemini_video_report.json",
            mime="application/json",
            use_container_width=True,
        )

else:
    if uploaded_file is not None:
        st.info("Video ready. Confirm authorization above, then click **Analyze Class** to start the Gemini review.")
    else:
        st.info("Choose a video above to start a Gemini review.")
