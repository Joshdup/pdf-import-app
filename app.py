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
    # Updated regex to handle ABSA format: "1 Apr 2016  Description  Amount  Balance"
    # and flexible date formats
    lines = text.split('\n')
    transactions = []
    
    # ABSA date format: "1 Apr 2016", "13 Apr 2016", etc.
    date_pattern = r'^(\d{1,2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec|Jen|Feb|Mrt|Apr|Mei|Jun|Jul|Aug|Sep|Okt|Nov|Des)\s+(\d{4})'
    
    # Amount pattern: handles "123,45" or "123 456,78" or "123,45 -" (negative)
    amount_pattern = r'(\d{1,3}(?:\s?\d{3})*(?:,\d{2})?)\s*(-)?'
    
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        
        # Check if line starts with a date
        date_match = re.match(date_pattern, line, re.IGNORECASE)
        if date_match:
            day, month_str, year = date_match.groups()
            
            # Map month names (English and Afrikaans)
            month_map = {
                'Jan': '01', 'Jen': '01', 'Feb': '02', 'Mrt': '03', 'Mar': '03',
                'Apr': '04', 'Mei': '05', 'May': '05', 'Jun': '06', 'Jul': '07',
                'Aug': '08', 'Sep': '09', 'Okt': '10', 'Oct': '10', 'Nov': '11', 'Des': '12', 'Dec': '12'
            }
            month = month_map.get(month_str, '01')
            date_value = f"{year}-{month}-{day.zfill(2)}"
            
            # Extract description and amounts from the same line
            rest_of_line = line[date_match.end():].strip()
            
            # Find all amounts in the line (description followed by amounts)
            # The last amount before end or the pattern is usually the transaction amount
            amounts = re.findall(amount_pattern, rest_of_line)
            
            if amounts:
                # Get the last substantial amount (not just trailing whitespace)
                for amount_str, is_negative in reversed(amounts):
                    try:
                        # Parse amount: remove spaces, replace comma with dot
                        parsed_amount = float(amount_str.replace(' ', '').replace(',', '.'))
                        if is_negative:
                            parsed_amount = -parsed_amount
                        
                        # Extract description (everything before the amount)
                        amount_start = rest_of_line.rfind(amount_str)
                        if amount_start > 0:
                            description = rest_of_line[:amount_start].strip()
                        else:
                            description = "Transaction"
                        
                        # Continue reading next lines if they are part of the same transaction
                        j = i + 1
                        while j < len(lines):
                            next_line = lines[j].strip()
                            # Stop if we hit another date or an empty line
                            if not next_line or re.match(date_pattern, next_line, re.IGNORECASE):
                                break
                            # Add to description if it looks like a detail line
                            if next_line and not re.match(r'^\d', next_line):
                                description += " " + next_line
                            j += 1
                        
                        category = categorize(description)
                        people = identify_people(description)
                        
                        transactions.append({
                            "Date": date_value,
                            "Description": description.strip(),
                            "Amount": round(parsed_amount, 2),
                            "Category": category,
                            "People Mentioned": people,
                            "Source": source_label
                        })
                        
                        i = j - 1
                        break
                    except (ValueError, IndexError):
                        pass
        
        i += 1
    
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
