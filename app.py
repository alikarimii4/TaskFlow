
from flask import Flask, render_template, request, redirect, url_for, flash
from database import get_connection, init_db
import jdatetime
from datetime import date


app = Flask(__name__)
app.secret_key = "taskflow-local-secret-key"

# Create the database and tasks table
init_db()


def normalize_digits(value):
    """Convert Persian and Arabic digits to English digits."""
    persian_digits = "۰۱۲۳۴۵۶۷۸۹"
    arabic_digits = "٠١٢٣٤٥٦٧٨٩"

    for index in range(10):
        value = value.replace(persian_digits[index], str(index))
        value = value.replace(arabic_digits[index], str(index))

    return value


def jalali_to_gregorian(value):
    """Convert a Jalali date string to Gregorian ISO format."""
    if not value:
        return None

    value = normalize_digits(value.strip())
    value = value.replace("-", "/").replace(".", "/")
    parts = value.split("/")

    if len(parts) != 3:
        raise ValueError("فرمت تاریخ صحیح نیست.")

    try:
        year, month, day = map(int, parts)
        jalali_date = jdatetime.date(year, month, day)
        return jalali_date.togregorian().isoformat()
    except (ValueError, TypeError):
        raise ValueError("تاریخ شمسی واردشده معتبر نیست.")


def gregorian_to_jalali(value):
    """Convert a Gregorian ISO date to Jalali display format."""
    if not value:
        return ""

    gregorian_date = date.fromisoformat(value)
    jalali_date = jdatetime.date.fromgregorian(date=gregorian_date)

    return jalali_date.strftime("%Y/%m/%d")


def add_jalali_dates(tasks_list):
    """Add a Jalali display date to each task without changing its stored date."""
    result = []

    for task in tasks_list:
        task_data = dict(task)
        task_data["due_date_shamsi"] = gregorian_to_jalali(
            task_data["due_date"]
        )
        result.append(task_data)

    return result


@app.route("/")
def home():
    return redirect(url_for("dashboard"))


@app.route("/dashboard")
def dashboard():
    connection = get_connection()

    total_tasks = connection.execute(
        "SELECT COUNT(*) FROM tasks"
    ).fetchone()[0]

    pending_tasks = connection.execute(
        "SELECT COUNT(*) FROM tasks WHERE status = ?",
        ("pending",)
    ).fetchone()[0]

    in_progress_tasks = connection.execute(
        "SELECT COUNT(*) FROM tasks WHERE status = ?",
        ("in_progress",)
    ).fetchone()[0]

    completed_tasks = connection.execute(
        "SELECT COUNT(*) FROM tasks WHERE status = ?",
        ("completed",)
    ).fetchone()[0]

    connection.close()

    return render_template(
        "dashboard.html",
        total_tasks=total_tasks,
        pending_tasks=pending_tasks,
        in_progress_tasks=in_progress_tasks,
        completed_tasks=completed_tasks
    )


@app.route("/tasks")
def tasks():
    search = request.args.get("search", "").strip()
    selected_status = request.args.get("status", "")
    selected_priority = request.args.get("priority", "")

    allowed_statuses = ("pending", "in_progress", "completed")
    allowed_priorities = ("high", "medium", "low")

    if selected_status not in allowed_statuses:
        selected_status = ""

    if selected_priority not in allowed_priorities:
        selected_priority = ""

    query = """
        SELECT *,
        CASE
            WHEN due_date IS NOT NULL
            AND due_date < date('now', 'localtime')
            AND status != 'completed'
            THEN 1
            ELSE 0
        END AS is_overdue
        FROM tasks
        WHERE 1=1
    """

    parameters = []

    if search:
        query += " AND title LIKE ?"
        parameters.append(f"%{search}%")

    if selected_status:
        query += " AND status = ?"
        parameters.append(selected_status)

    if selected_priority:
        query += " AND priority = ?"
        parameters.append(selected_priority)

    query += " ORDER BY id DESC"

    connection = get_connection()
    tasks_list = connection.execute(
        query, parameters
    ).fetchall()
    connection.close()

    tasks_list = add_jalali_dates(tasks_list)

    return render_template(
        "tasks.html",
        tasks=tasks_list,
        search=search,
        selected_status=selected_status,
        selected_priority=selected_priority
    )


@app.route("/tasks/add", methods=["GET", "POST"])
def add_task():
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip()
        priority = request.form.get("priority", "medium")
        entered_due_date = request.form.get("due_date", "").strip()

        if not title:
            flash("وارد کردن عنوان وظیفه الزامی است.", "danger")
            return redirect(url_for("add_task"))

        if priority not in ("high", "medium", "low"):
            flash("اولویت انتخاب‌شده معتبر نیست.", "danger")
            return redirect(url_for("add_task"))

        try:
            due_date = jalali_to_gregorian(entered_due_date)
        except ValueError as error:
            flash(str(error), "danger")
            return redirect(url_for("add_task"))

        connection = get_connection()
        connection.execute(
            """
            INSERT INTO tasks (title, description, priority, due_date)
            VALUES (?, ?, ?, ?)
            """,
            (title, description, priority, due_date)
        )
        connection.commit()
        connection.close()

        flash("وظیفه با موفقیت ثبت شد.", "success")
        return redirect(url_for("tasks"))

    return render_template("add_task.html")


@app.route("/tasks/<int:task_id>/edit", methods=["GET", "POST"])
def edit_task(task_id):
    connection = get_connection()

    task = connection.execute(
        "SELECT * FROM tasks WHERE id = ?",
        (task_id,)
    ).fetchone()

    if task is None:
        connection.close()
        flash("وظیفه موردنظر پیدا نشد.", "danger")
        return redirect(url_for("tasks"))

    if request.method == "POST":
        title = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip()
        priority = request.form.get("priority", "")
        status = request.form.get("status", "")
        entered_due_date = request.form.get("due_date", "").strip()

        if not title:
            connection.close()
            flash("عنوان وظیفه نمی‌تواند خالی باشد.", "danger")
            return redirect(url_for("edit_task", task_id=task_id))

        if priority not in ("high", "medium", "low"):
            connection.close()
            flash("اولویت انتخاب‌شده معتبر نیست.", "danger")
            return redirect(url_for("edit_task", task_id=task_id))

        if status not in ("pending", "in_progress", "completed"):
            connection.close()
            flash("وضعیت انتخاب‌شده معتبر نیست.", "danger")
            return redirect(url_for("edit_task", task_id=task_id))

        try:
            due_date = jalali_to_gregorian(entered_due_date)
        except ValueError as error:
            connection.close()
            flash(str(error), "danger")
            return redirect(url_for("edit_task", task_id=task_id))

        connection.execute(
            """
            UPDATE tasks
            SET title = ?, description = ?, priority = ?,
                status = ?, due_date = ?
            WHERE id = ?
            """,
            (title, description, priority, status, due_date, task_id)
        )
        connection.commit()
        connection.close()

        flash("تغییرات وظیفه ذخیره شد.", "success")
        return redirect(url_for("tasks"))

    connection.close()

    task_data = dict(task)
    task_data["due_date_shamsi"] = gregorian_to_jalali(
        task_data["due_date"]
    )

    return render_template("edit_task.html", task=task_data)


@app.route("/tasks/<int:task_id>/delete", methods=["POST"])
def delete_task(task_id):
    connection = get_connection()

    connection.execute(
        "DELETE FROM tasks WHERE id = ?",
        (task_id,)
    )

    connection.commit()
    connection.close()

    flash("وظیفه حذف شد.", "success")
    return redirect(url_for("tasks"))


if __name__ == "__main__":
    app.run(debug=True)
