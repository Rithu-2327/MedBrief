
from flask import (
    Flask, request, render_template, redirect,
    url_for, flash, send_file
)
import os
import re
import html
from io import BytesIO
from datetime import datetime
from werkzeug.utils import secure_filename
from reportlab.lib.pagesizes import A4
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, PageBreak
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT
from reportlab.lib import colors

from utils.ocr_handler import extract_text_tesseract
from utils.summarizer import generate_summary
from utils.entity_highlighter import highlight_medical_entities


# --------------------------------------------------
# Flask Configuration
# --------------------------------------------------

app = Flask(__name__, static_url_path="/static")
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "local-dev-key")

UPLOAD_FOLDER = os.path.join(app.root_path, "uploads")
ALLOWED_EXTENSIONS = {"pdf", "png", "jpg", "jpeg"}

app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # 16 MB

os.makedirs(UPLOAD_FOLDER, exist_ok=True)


# --------------------------------------------------
# Medical AI Disclaimer
# --------------------------------------------------

MEDICAL_DISCLAIMER = (
    "MedBrief AI uses artificial intelligence to summarize medical reports. "
    "AI can make mistakes, misinterpret medical terms, or omit important "
    "information. The generated summary is not guaranteed to be accurate "
    "or complete. This information is for informational purposes only and "
    "is not a substitute for professional medical advice, diagnosis, or "
    "treatment. Always check the original report and consult a qualified "
    "healthcare professional before making medical decisions."
)


# --------------------------------------------------
# Helper Functions
# --------------------------------------------------

def allowed_file(filename):
    return (
        bool(filename)
        and "." in filename
        and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS
    )


def clean_text_for_pdf(text):
    """
    Remove HTML markup, decode entities, and escape special characters
    before inserting user-provided text into ReportLab Paragraphs.
    """
    text = str(text or "")
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</p\s*>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]*>", "", text)
    text = html.unescape(text)

    # Escape XML-sensitive characters and preserve line breaks.
    lines = text.splitlines() or [text]
    return "<br/>".join(html.escape(line) or " " for line in lines)


# --------------------------------------------------
# Home Page
# --------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html")


# --------------------------------------------------
# Upload, OCR, Summarize, Highlight
# --------------------------------------------------

@app.route("/upload", methods=["POST"])
def upload_file():
    if "file" not in request.files:
        flash("Please select a file.")
        return redirect(url_for("index"))

    file = request.files["file"]

    if not file or not file.filename:
        flash("No file selected.")
        return redirect(url_for("index"))

    if not allowed_file(file.filename):
        flash("Unsupported file type. Upload PDF, PNG, JPG, or JPEG.")
        return redirect(url_for("index"))

    original_filename = secure_filename(file.filename)

    if not original_filename:
        flash("Invalid filename. Please choose another file.")
        return redirect(url_for("index"))

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    filename = f"{timestamp}_{original_filename}"
    filepath = os.path.join(app.config["UPLOAD_FOLDER"], filename)

    try:
        file.save(filepath)

        # Step 1: Extract text using OCR
        extracted_text = extract_text_tesseract(filepath)

        if not extracted_text or not extracted_text.strip():
            flash(
                "No readable text was found. Please check the document "
                "or upload a clearer scan."
            )
            return redirect(url_for("index"))

        # Step 2: Generate the AI summary
        summary = generate_summary(extracted_text)

        if not summary or not str(summary).strip():
            flash(
                "A summary could not be generated. Please try another report."
            )
            return redirect(url_for("index"))

        # Step 3: Highlight medical terms
        highlighted_text = highlight_medical_entities(extracted_text)

        return render_template(
            "summary.html",
            extracted_text=highlighted_text,
            summary=summary,
            disclaimer=MEDICAL_DISCLAIMER
        )

    except Exception:
        app.logger.exception("Medical report processing failed.")
        flash(
            "The report could not be processed. Please try another file "
            "or a clearer scan."
        )
        return redirect(url_for("index"))

    finally:
        # Delete the temporary uploaded file after processing.
        try:
            if os.path.exists(filepath):
                os.remove(filepath)
        except OSError:
            app.logger.exception("Could not delete temporary uploaded file.")


# --------------------------------------------------
# PDF Export
# --------------------------------------------------

@app.route("/export-pdf", methods=["POST"])
def export_pdf():
    extracted_text = request.form.get("extracted_text", "")
    summary = request.form.get("summary", "")

    if not summary.strip():
        flash("No summary is available to export.")
        return redirect(url_for("index"))

    buffer = BytesIO()

    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=50,
        leftMargin=50,
        topMargin=50,
        bottomMargin=50
    )

    styles = getSampleStyleSheet()

    styles.add(ParagraphStyle(
        name="ReportTitle",
        parent=styles["Title"],
        fontSize=18,
        leading=23,
        textColor=colors.HexColor("#003366"),
        alignment=TA_LEFT,
        spaceAfter=18
    ))

    styles.add(ParagraphStyle(
        name="ReportHeading",
        parent=styles["Heading2"],
        fontSize=13,
        leading=17,
        textColor=colors.HexColor("#072d58"),
        spaceBefore=8,
        spaceAfter=10
    ))

    styles.add(ParagraphStyle(
        name="ReportBody",
        parent=styles["BodyText"],
        fontSize=9,
        leading=13,
        alignment=TA_LEFT,
        spaceAfter=8,
        wordWrap="CJK"
    ))

    styles.add(ParagraphStyle(
        name="Disclaimer",
        parent=styles["BodyText"],
        fontSize=9,
        leading=13,
        textColor=colors.HexColor("#493b16"),
        backColor=colors.HexColor("#fff8e6"),
        borderColor=colors.HexColor("#e8c766"),
        borderWidth=1,
        borderPadding=8,
        spaceBefore=8,
        spaceAfter=12
    ))

    story = []

    # Document title
    story.append(Paragraph("MedBrief AI", styles["ReportTitle"]))
    story.append(Paragraph(
        "Medical Report Summary",
        styles["ReportHeading"]
    ))

    # AI-generated summary
    story.append(Paragraph(
        "AI-Generated Summary",
        styles["ReportHeading"]
    ))
    story.append(Paragraph(
        clean_text_for_pdf(summary),
        styles["ReportBody"]
    ))

    # Medical disclaimer
    story.append(Paragraph(
        "IMPORTANT MEDICAL DISCLAIMER",
        styles["ReportHeading"]
    ))
    story.append(Paragraph(
        clean_text_for_pdf(MEDICAL_DISCLAIMER),
        styles["Disclaimer"]
    ))

    # Extracted source text
    if extracted_text.strip():
        story.append(PageBreak())
        story.append(Paragraph(
            "Extracted Text from Original Report",
            styles["ReportHeading"]
        ))
        story.append(Paragraph(
            clean_text_for_pdf(extracted_text),
            styles["ReportBody"]
        ))

    doc.build(story)
    buffer.seek(0)

    return send_file(
        buffer,
        as_attachment=True,
        download_name="MedBrief_AI_Report_Summary.pdf",
        mimetype="application/pdf"
    )


# --------------------------------------------------
# Upload Size Error
# --------------------------------------------------

@app.errorhandler(413)
def file_too_large(error):
    flash("The file is too large. Maximum upload size is 16 MB.")
    return redirect(url_for("index"))


# --------------------------------------------------
# Run Application
# --------------------------------------------------

if __name__ == "__main__":
    app.run(debug=True)