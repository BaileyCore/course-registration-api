from fastapi import FastAPI, UploadFile, File, HTTPException
from bs4 import BeautifulSoup
import re

app = FastAPI(
    title="Course Catalog API",
    version="1.0.0"
)

# In-memory storage for imported courses
courses = {}


def normalize_course_code(code: str) -> str:
    """
    Converts course codes to one consistent format.

    Examples:
    COSC 3506 -> COSC3506
    cosc3506  -> COSC3506
    """
    return re.sub(r"\s+", "", code).upper()


def extract_course_codes(text: str) -> list[str]:
    """
    Extract course codes from prerequisite/cross-listed text.

    Example:
    'Requires COSC 1046 and either COSC 1047 or ITEC 1047'

    becomes:
    ['COSC1046', 'COSC1047', 'ITEC1047']
    """
    if not text:
        return []

    text = text.strip()

    if text.lower() in {"none", "n/a", "na", "-"}:
        return []

    matches = re.findall(
        r"\b([A-Za-z]{2,})\s*[- ]?\s*(\d{3,4}[A-Za-z]?)\b",
        text
    )

    result = []

    for department, number in matches:
        code = f"{department.upper()}{number.upper()}"

        if code not in result:
            result.append(code)

    return result


@app.get("/")
def root():
    return {
        "message": "Course Registration API is running"
    }


@app.post("/api/v1/admin/catalog/import")
async def import_catalog(file: UploadFile = File(...)):

    # Read uploaded file
    contents = await file.read()

    # Decode HTML
    try:
        html = contents.decode("utf-8")
    except UnicodeDecodeError:
        html = contents.decode("latin-1")

    # Parse HTML
    soup = BeautifulSoup(html, "html.parser")

    table = soup.find("table")

    if table is None:
        raise HTTPException(
            status_code=400,
            detail="No course table found in uploaded HTML"
        )

    rows = table.find_all("tr")

    if len(rows) < 2:
        raise HTTPException(
            status_code=400,
            detail="Course table contains no course data"
        )

    # Read table headers dynamically
    header_cells = rows[0].find_all(["th", "td"])

    headers = [
        cell.get_text(" ", strip=True).lower()
        for cell in header_cells
    ]

    # Determine column positions from header names
    column_map = {}

    for index, header in enumerate(headers):

        normalized_header = re.sub(r"[^a-z]", "", header)

        if "coursecode" in normalized_header:
            column_map["course_code"] = index

        elif normalized_header == "title":
            column_map["title"] = index

        elif "credit" in normalized_header:
            column_map["credits"] = index

        elif "prerequisite" in normalized_header:
            column_map["prerequisites"] = index

        elif "crosslisted" in normalized_header or "crosslist" in normalized_header:
            column_map["cross_listed"] = index

    required_columns = {
        "course_code",
        "title",
        "credits",
        "prerequisites",
        "cross_listed"
    }

    if not required_columns.issubset(column_map):
        raise HTTPException(
            status_code=400,
            detail="Course table is missing one or more required columns"
        )

    imported_courses = {}

    # Process every course row
    for row in rows[1:]:

        cells = row.find_all(["td", "th"])

        if not cells:
            continue

        values = [
            cell.get_text(" ", strip=True)
            for cell in cells
        ]

        # Skip malformed rows
        if len(values) <= max(column_map.values()):
            continue

        raw_code = values[column_map["course_code"]].strip()

        if not raw_code:
            continue

        course_code = normalize_course_code(raw_code)

        title = values[column_map["title"]].strip()
        credits_text = values[column_map["credits"]].strip()

        prerequisites_text = values[
            column_map["prerequisites"]
        ].strip()

        cross_listed_text = values[
            column_map["cross_listed"]
        ].strip()

        # Convert credits to a number where possible
        try:
            credits_number = float(credits_text)

            if credits_number.is_integer():
                credits_number = int(credits_number)

        except ValueError:
            credits_number = credits_text

        course = {
            "course_code": course_code,
            "title": title,
            "credits": credits_number,
            "prerequisites": extract_course_codes(
                prerequisites_text
            ),
            "cross_listed": extract_course_codes(
                cross_listed_text
            )
        }

        imported_courses[course_code] = course

    if not imported_courses:
        raise HTTPException(
            status_code=400,
            detail="No valid courses were found in the uploaded catalog"
        )

    # Replace the currently stored catalog
    courses.clear()
    courses.update(imported_courses)

    return {
        "message": "Catalog imported successfully",
        "courses_imported": len(courses)
    }


@app.get("/api/v1/catalog/courses/{course_code}")
def get_course(course_code: str):

    normalized_code = normalize_course_code(course_code)

    if normalized_code not in courses:
        raise HTTPException(
            status_code=404,
            detail="Course not found"
        )

    return courses[normalized_code]