import io
import os
import re
import time
from datetime import datetime

import pandas as pd
import pdfplumber
import pytesseract
from flask import Flask, flash, redirect, render_template, request, send_from_directory, url_for
from PIL import Image

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "replace-with-a-secure-key")
app.config["UPLOAD_FOLDER"] = "uploads"
app.config["EXPORT_FOLDER"] = "exports"
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024

pytesseract.pytesseract.tesseract_cmd = os.environ.get("TESSERACT_CMD", r"C:\Program Files\Tesseract-OCR\tesseract.exe")

os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
os.makedirs(app.config["EXPORT_FOLDER"], exist_ok=True)

ALLOWED_EXTENSIONS = {"pdf", "png", "jpg", "jpeg", "tif", "tiff"}
PERSON_1 = "John"
PERSON_2 = "Mike"

CATEGORIES = {
    "Pick n Pay": "Groceries",
    "Shoprite": "Groceries",
    "Shell": "Fuel",
    "Engen": "Fuel",
    "Salary": "Income",
    "Transfer": "Transfer",
    "Payment": "Transfer",
    "Rent": "Bills",
    "Electricity": "Bills"
}


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def extract_text_from_image(image_path):
    image = Image.open(image_path)
    return pytesseract.image_to_string(image)


def extract_text_from_pdf(pdf_path):
    text = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text:
                text.append(page_text)
    return "\n".join(text)


def normalize_date(value):
    value = value.replace("-", "/")
    parts = value.split("/")
    if len(parts) != 3:
        return value
    month, day, year = parts
    if len(year) == 2:
        year = "20" + year
    try:
        parsed = datetime.strptime(f"{month}/{day}/{year}", "%m/%d/%Y")
    except ValueError:
        try:
            parsed = datetime.strptime(f"{day}/{month}/{year}", "%d/%m/%Y")
        except ValueError:
            return value
    return parsed.strftime("%Y-%m-%d")


def parse_amount(value):
    cleaned = value.replace(",", "").replace("$", "")
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def categorize(description):
    for keyword, category in CATEGORIES.items():
        if keyword.lower() in description.lower():
            return category
    return "Other"


def identify_people(description):
    description_lower = description.lower()
    people = []
    if PERSON_1.lower() in description_lower:
        people.append(PERSON_1)
    if PERSON_2.lower() in description_lower:
        people.append(PERSON_2)
    if not people and "transfer" in description_lower:
        people.append("Transfer")
    return ", ".join(people) if people else "Other"


def parse_transactions(text, source_label):
    pattern = r"(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})\s+(.+?)\s+(-?\$?\d{1,3}(?:,\d{3})*(?:\.\d{2})?)"
    matches = re.findall(pattern, text)
    transactions = []
    for date_text, description, amount_text in matches:
        date_value = normalize_date(date_text)
        amount = parse_amount(amount_text)
        category = categorize(description)
        people = identify_people(description)
        transactions.append({
            "Date": date_value,
            "Description": description.strip(),
            "Amount": amount,
            "Category": category,
            "People Mentioned": people,
            "Source": source_label
        })
    return transactions


def build_summary(transactions):
    category_totals = {}
    people_totals = {}
    total_amount = 0.0
    for item in transactions:
        category_totals[item["Category"]] = category_totals.get(item["Category"], 0.0) + item["Amount"]
        for person in item["People Mentioned"].split(", "):
            people_totals[person] = people_totals.get(person, 0.0) + item["Amount"]
        total_amount += item["Amount"]
    return {
        "count": len(transactions),
        "total_amount": total_amount,
        "category_totals": category_totals,
        "people_totals": people_totals
    }


def create_excel(transactions):
    export_filename = f"transactions_{int(time.time())}.xlsx"
    export_path = os.path.join(app.config["EXPORT_FOLDER"], export_filename)
    df = pd.DataFrame(transactions)
    with pd.ExcelWriter(export_path, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Transactions")
        summary_rows = []
        summary_rows.append({"Metric": "Transaction Count", "Value": len(transactions)})
        summary_rows.append({"Metric": "Total Amount", "Value": round(sum(t["Amount"] for t in transactions), 2)})
        pd.DataFrame(summary_rows).to_excel(writer, index=False, sheet_name="Summary")
        pd.DataFrame([
            {"Category": k, "Total": v} for k, v in build_summary(transactions)["category_totals"].items()
        ]).to_excel(writer, index=False, sheet_name="Category Totals")
        pd.DataFrame([
            {"Person": k, "Total": v} for k, v in build_summary(transactions)["people_totals"].items()
        ]).to_excel(writer, index=False, sheet_name="People Totals")
    return export_filename


@app.route("/", methods=["GET", "POST"])
def index():
    result_text = None
    transactions = []
    summary = None
    download_link = None

    if request.method == "POST":
        uploaded_files = request.files.getlist("documents")
        if not uploaded_files or uploaded_files[0].filename == "":
            flash("Please choose at least one PDF or image file.", "warning")
            return redirect(request.url)

        combined_text = []
        for uploaded_file in uploaded_files:
            if uploaded_file and allowed_file(uploaded_file.filename):
                filename = uploaded_file.filename
                save_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
                uploaded_file.save(save_path)
                ext = filename.rsplit(".", 1)[1].lower()
                if ext == "pdf":
                    extracted = extract_text_from_pdf(save_path)
                else:
                    extracted = extract_text_from_image(save_path)
                combined_text.append(f"--- {filename} ---")
                combined_text.append(extracted)
                transactions.extend(parse_transactions(extracted, filename))
            else:
                flash(f"Skipped unsupported file: {uploaded_file.filename}", "error")

        result_text = "\n\n".join(combined_text).strip()
        if not result_text:
            flash("No text could be extracted from the selected files.", "warning")

        if transactions:
            summary = build_summary(transactions)
            export_filename = create_excel(transactions)
            download_link = url_for("download_file", filename=export_filename)
        else:
            flash("No transactions could be parsed from the uploaded files.", "warning")

    return render_template(
        "index.html",
        result_text=result_text,
        transactions=transactions,
        summary=summary,
        download_link=download_link,
    )


@app.route("/download/<path:filename>")
def download_file(filename):
    return send_from_directory(app.config["EXPORT_FOLDER"], filename, as_attachment=True)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=True)
