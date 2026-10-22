import csv
import hashlib
import secrets
import smtplib
import time
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path

import streamlit as st

# ---------------- Configuration ----------------
st.set_page_config(
    page_title="Library Management System",
    page_icon="📚",
    layout="wide",
)

DATA_DIR = Path(__file__).parent
BOOKS_FILE = DATA_DIR / "book_data.txt"
USERS_FILE = DATA_DIR / "user_data.txt"
ISSUES_FILE = DATA_DIR / "issue_data.txt"

OTP_TTL = 300          # OTP valid for 5 minutes
MAX_ATTEMPTS = 5       # wrong guesses allowed per code
RESEND_COOLDOWN = 30   # seconds between resend requests


# ---------------- Authentication (Gmail OTP) ----------------
def hash_otp(otp: str) -> str:
    return hashlib.sha256(otp.encode()).hexdigest()


def send_otp_email(to_addr: str, otp: str) -> None:
    cfg = st.secrets["email"]
    msg = EmailMessage()
    msg["Subject"] = "Your Library System login code"
    msg["From"] = cfg["sender"]
    msg["To"] = to_addr
    msg.set_content(
        f"Your one-time code is {otp}.\n"
        f"It expires in {OTP_TTL // 60} minutes. "
        "If you didn't request it, you can ignore this email."
    )
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=15) as server:
        server.login(cfg["sender"], cfg["app_password"].replace(" ", ""))
        server.send_message(msg)


def start_otp(email: str) -> bool:
    otp = f"{secrets.randbelow(10**6):06d}"  # cryptographically secure
    try:
        send_otp_email(email, otp)
    except (smtplib.SMTPException, OSError):
        st.error("Could not send the email. Check your secrets.toml and Gmail App Password.")
        return False
    st.session_state.update(
        otp_hash=hash_otp(otp),
        otp_email=email,
        otp_expires=time.time() + OTP_TTL,
        otp_sent_at=time.time(),
        otp_attempts=0,
    )
    return True


def require_login() -> None:
    """Block the rest of the app until the user has verified an OTP."""
    if st.session_state.get("authenticated"):
        return

    st.title("🔐 Library Login")
    allowed = {e.lower() for e in st.secrets["auth"]["allowed_emails"]}

    # Step 1: ask for email
    if "otp_hash" not in st.session_state:
        with st.form("email_form"):
            email = st.text_input("Email address").strip().lower()
            go = st.form_submit_button("Send code", type="primary")
        if go:
            if email in allowed:
                if start_otp(email):
                    st.rerun()
            else:
                # Same message as success so admin emails aren't revealed
                st.info("Code will only be sent to Authorised emails.")
        st.stop()

    # Step 2: verify code
    st.write(f"A 6-digit code was sent to **{st.session_state['otp_email']}**.")
    with st.form("otp_form"):
        code = st.text_input("Enter code", max_chars=6).strip()
        verify = st.form_submit_button("Verify", type="primary")

    if verify:
        if time.time() > st.session_state["otp_expires"]:
            st.error("Code expired. Request a new one.")
        elif st.session_state["otp_attempts"] >= MAX_ATTEMPTS:
            st.error("Too many attempts. Request a new code.")
        elif secrets.compare_digest(hash_otp(code), st.session_state["otp_hash"]):
            for key in ("otp_hash", "otp_expires", "otp_sent_at", "otp_attempts"):
                st.session_state.pop(key, None)
            st.session_state["authenticated"] = True
            st.rerun()
        else:
            st.session_state["otp_attempts"] += 1
            left = MAX_ATTEMPTS - st.session_state["otp_attempts"]
            st.error(f"Incorrect code. {left} attempt(s) left.")

    col_a, col_b = st.columns(2)
    wait = RESEND_COOLDOWN - (time.time() - st.session_state["otp_sent_at"])
    if col_a.button("Resend code", disabled=wait > 0):
        if start_otp(st.session_state["otp_email"]):
            st.rerun()
    if wait > 0:
        col_a.caption(f"You can resend in {int(wait) + 1}s (interact with the page to refresh).")
    if col_b.button("Use a different email"):
        for key in list(st.session_state.keys()):
            if key.startswith("otp_"):
                del st.session_state[key]
        st.rerun()
    st.stop()


require_login()  # nothing below runs unless the user is authenticated


# ---------------- File helpers ----------------
def read_records(path, expected_fields):
    """Read CSV-formatted records from a local text file."""
    if not path.exists():
        return []
    records = []
    try:
        with path.open("r", newline="", encoding="utf-8") as file:
            for row in csv.reader(file):
                if len(row) == expected_fields:
                    records.append([value.strip() for value in row])
    except (OSError, csv.Error):
        st.error(f"Could not read {path.name}. Check the file and try again.")
    return records


def write_records(path, records):
    """Replace a data file with the supplied records."""
    try:
        with path.open("w", newline="", encoding="utf-8") as file:
            csv.writer(file).writerows(records)
        return True
    except OSError as exc:
        st.error(f"Could not save {path.name}: {exc}")
        return False


def next_id(records):
    numeric_ids = [int(row[0]) for row in records if row and row[0].isdigit()]
    return max(numeric_ids, default=0) + 1


def find_book(books, query):
    query = query.strip().casefold()
    if not query:
        return None
    for book in books:
        if book[0] == query or book[1].casefold() == query:
            return book
    return None


def find_user(users, user_id):
    return next((user for user in users if user[0] == user_id.strip()), None)


# ---------------- Load data ----------------
books = read_records(BOOKS_FILE, 4)
users = read_records(USERS_FILE, 3)
issues = read_records(ISSUES_FILE, 5)

# ---------------- Styling ----------------
st.markdown(
    """
    <style>
    .block-container {padding-top: 2rem; padding-bottom: 3rem;}
    [data-testid="stMetric"] {
        border: 1px solid rgba(128,128,128,.25);
        padding: 1rem;
        border-radius: 12px;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("📚 Library Management System")
st.caption("Manage books, members, and lending from one place.")

with st.sidebar:
    st.header("Navigation")
    page = st.radio(
        "Choose a section",
        [
            "Dashboard",
            "Add Book",
            "View / Search Books",
            "Register User",
            "Issue Book",
            "Return Book",
            "Issue History",
        ],
    )
    st.divider()
    st.caption(f"Signed in as {st.session_state.get('otp_email', 'admin')}")
    if st.button("Log out"):
        st.session_state.clear()
        st.rerun()
    st.caption("Local file storage • Python + Streamlit")

# ---------------- Dashboard ----------------
if page == "Dashboard":
    active_issues = [issue for issue in issues if issue[4].casefold() == "issued"]
    total_copies = sum(int(b[3]) for b in books if b[3].isdigit())

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Book titles", len(books))
    col2.metric("Available copies", total_copies)
    col3.metric("Registered users", len(users))
    col4.metric("Books currently issued", len(active_issues))

    st.subheader("Recently added books")
    if books:
        recent = books[-5:][::-1]
        st.dataframe(
            [{"Book ID": b[0], "Book Name": b[1], "Author": b[2], "Available": b[3]}
             for b in recent],
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("No books have been added yet. Open **Add Book** to get started.")

    st.subheader("Quick guide")
    st.markdown(
        """
        1. Add book titles and their available quantities.
        2. Register library users.
        3. Issue a book to a registered user.
        4. Use Return Book when the book comes back.
        """
    )

# ---------------- Add book ----------------
elif page == "Add Book":
    st.subheader("Add a new book")
    with st.form("add_book_form", clear_on_submit=True):
        book_name = st.text_input("Book name")
        author = st.text_input("Author")
        quantity = st.number_input("Quantity", min_value=1, max_value=100000, value=1, step=1)
        submitted = st.form_submit_button("Add book", type="primary")

    if submitted:
        book_name = book_name.strip()
        author = author.strip()
        if not book_name or not author:
            st.error("Please enter both a book name and an author.")
        elif any(b[1].casefold() == book_name.casefold() for b in books):
            st.warning("A book with this name already exists. Use the existing record instead.")
        else:
            book_id = str(next_id(books))
            updated_books = books + [[book_id, book_name, author, str(int(quantity))]]
            if write_records(BOOKS_FILE, updated_books):
                books = updated_books
                st.success(f"Added **{book_name}** successfully. Book ID: **{book_id}**")

# ---------------- View / Search ----------------
elif page == "View / Search Books":
    st.subheader("Book catalogue")
    query = st.text_input("Search by book ID or title", placeholder="e.g. 3 or Harry Potter")
    filtered = books
    if query.strip():
        normalized = query.strip().casefold()
        filtered = [
            b for b in books
            if b[0] == normalized or normalized in b[1].casefold()
        ]

    if filtered:
        st.dataframe(
            [{"Book ID": b[0], "Book Name": b[1], "Author": b[2], "Available Copies": b[3]}
             for b in filtered],
            use_container_width=True,
            hide_index=True,
        )
        if query.strip():
            exact = find_book(books, query)
            if exact:
                st.success(f"Exact match: {exact[1]} (ID {exact[0]})")
    else:
        st.info("No matching books found." if query.strip() else "No books in the catalogue yet.")

# ---------------- Register user ----------------
elif page == "Register User":
    st.subheader("Register a library user")
    with st.form("register_user_form", clear_on_submit=True):
        user_name = st.text_input("Full name")
        email = st.text_input("Email address (optional)")
        submitted = st.form_submit_button("Register user", type="primary")

    if submitted:
        user_name = user_name.strip()
        email = email.strip()
        if not user_name:
            st.error("Please enter the user's name.")
        elif any(u[1].casefold() == user_name.casefold() for u in users):
            st.warning("A user with this name is already registered.")
        else:
            user_id = str(next_id(users))
            updated_users = users + [[user_id, user_name, email]]
            if write_records(USERS_FILE, updated_users):
                users = updated_users
                st.success(f"Registered **{user_name}**. User ID: **{user_id}**")

    st.divider()
    st.subheader("Registered users")
    if users:
        st.dataframe(
            [{"User ID": u[0], "Name": u[1], "Email": u[2] or "—"} for u in users],
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("No users registered yet.")

# ---------------- Issue book ----------------
elif page == "Issue Book":
    st.subheader("Issue a book")
    available_books = [b for b in books if b[3].isdigit() and int(b[3]) > 0]
    if not users:
        st.warning("Register a user before issuing a book.")
    elif not available_books:
        st.warning("No books are currently available to issue.")
    else:
        user_options = {f"{u[1]} (ID {u[0]})": u[0] for u in users}
        book_options = {
            f"{b[1]} — {b[2]} (ID {b[0]}, available: {b[3]})": b[0]
            for b in available_books
        }

        with st.form("issue_book_form", clear_on_submit=True):
            selected_user_label = st.selectbox("Registered user", list(user_options))
            selected_book_label = st.selectbox("Book", list(book_options))
            submitted = st.form_submit_button("Issue book", type="primary")

        if submitted:
            user_id = user_options[selected_user_label]
            book_id = book_options[selected_book_label]
            current_books = read_records(BOOKS_FILE, 4)
            current_issues = read_records(ISSUES_FILE, 5)
            book = next((b for b in current_books if b[0] == book_id), None)

            if not book or not book[3].isdigit() or int(book[3]) < 1:
                st.error("This book is no longer available.")
            else:
                book[3] = str(int(book[3]) - 1)
                issue_id = str(next_id(current_issues))
                issue_date = datetime.now().strftime("%Y-%m-%d")
                new_issue = [issue_id, user_id, book_id, issue_date, "issued"]
                if write_records(BOOKS_FILE, current_books):
                    if write_records(ISSUES_FILE, current_issues + [new_issue]):
                        st.success(
                            f"Issued **{book[1]}** to **{selected_user_label}** on {issue_date}."
                        )
                        st.info(f"Remaining copies: {book[3]}")

# ---------------- Return book ----------------
elif page == "Return Book":
    st.subheader("Return an issued book")
    active_issues = [i for i in issues if i[4].casefold() == "issued"]

    if not active_issues:
        st.info("There are no books awaiting return.")
    else:
        active_options = {}
        for issue in active_issues:
            user = find_user(users, issue[1])
            book = next((b for b in books if b[0] == issue[2]), None)
            user_label = user[1] if user else f"User {issue[1]}"
            book_label = book[1] if book else f"Book {issue[2]}"
            active_options[
                f"Issue #{issue[0]} — {book_label} / {user_label} (issued {issue[3]})"
            ] = issue[0]

        with st.form("return_book_form"):
            selected_label = st.selectbox("Select an issued book", list(active_options))
            submitted = st.form_submit_button("Confirm return", type="primary")

        if submitted:
            issue_id = active_options[selected_label]
            current_issues = read_records(ISSUES_FILE, 5)
            current_books = read_records(BOOKS_FILE, 4)
            target_issue = next(
                (i for i in current_issues if i[0] == issue_id and i[4].casefold() == "issued"),
                None,
            )
            target_book = (
                next((b for b in current_books if b[0] == target_issue[2]), None)
                if target_issue else None
            )

            if not target_issue or not target_book:
                st.error("Could not find this issue record or book.")
            elif not target_book[3].isdigit():
                st.error("The stored book quantity is invalid.")
            else:
                target_book[3] = str(int(target_book[3]) + 1)
                target_issue[4] = "returned"
                if write_records(BOOKS_FILE, current_books) and write_records(ISSUES_FILE, current_issues):
                    st.success(f"Return recorded for **{target_book[1]}**.")

# ---------------- History ----------------
elif page == "Issue History":
    st.subheader("Issue history")
    if issues:
        history_rows = []
        for issue in issues[::-1]:
            user = find_user(users, issue[1])
            book = next((b for b in books if b[0] == issue[2]), None)
            history_rows.append({
                "Issue ID": issue[0],
                "User": user[1] if user else f"User {issue[1]}",
                "Book": book[1] if book else f"Book {issue[2]}",
                "Issue Date": issue[3],
                "Status": issue[4].title(),
            })
        st.dataframe(history_rows, use_container_width=True, hide_index=True)
    else:
        st.info("No issue records yet.")