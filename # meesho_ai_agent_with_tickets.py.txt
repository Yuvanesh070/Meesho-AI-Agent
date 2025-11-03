# meesho_ai_agent_with_tickets.py
import streamlit as st
import pandas as pd
import os
import time
import requests
import csv
from datetime import datetime
from dotenv import load_dotenv
import openai
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# ---------- Load config ----------
load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL")
SMTP_SERVER = os.getenv("SMTP_SERVER")
SMTP_PORT = int(os.getenv("SMTP_PORT") or 587)
EMAIL_USERNAME = os.getenv("EMAIL_USERNAME")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
USE_EMAIL_ALERTS = os.getenv("USE_EMAIL_ALERTS", "false").lower() == "true"

if not OPENAI_API_KEY:
    st.error("Please set OPENAI_API_KEY in your .env file.")
    st.stop()

openai.api_key = OPENAI_API_KEY

# ---------- App config ----------
st.set_page_config(page_title="Meesho Supplier Quality AI + Tickets", layout="wide")
st.title("🧠 Meesho Supplier Quality AI Agent — Auto Tickets & Alerts")
st.markdown("Upload complaints; supplier-related complaints will auto-create tickets and send alerts.")

# Ticket file
TICKETS_FILE = "tickets.csv"

# Create tickets file header if not exists
if not os.path.exists(TICKETS_FILE):
    with open(TICKETS_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["Ticket_ID", "Complaint_ID", "Supplier", "Product", "Order_ID", "Issue", "Created_At", "Status", "Notes"])

# ---------- Helper functions ----------
def call_openai_classify(text):
    """
    Uses OpenAI ChatCompletion to classify complaint text.
    Returns one of: 'Supplier Issue', 'Logistics Issue', 'Customer Issue'
    """
    prompt = (
        "You are an assistant that classifies customer complaint text into exactly one of these categories: "
        "'Supplier Issue', 'Logistics Issue', 'Customer Issue'.\n\n"
        "Return only the category text (no extra words).\n\n"
        f"Complaint: \"{text}\""
    )

    try:
        resp = openai.ChatCompletion.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "user", "content": prompt}
            ],
            temperature=0
        )
        answer = resp["choices"][0]["message"]["content"].strip()
        # Normalize some variants
        if "supplier" in answer.lower():
            return "Supplier Issue"
        if "logistic" in answer.lower():
            return "Logistics Issue"
        return "Customer Issue"
    except Exception as e:
        st.warning(f"OpenAI error: {e}")
        return "Unknown"

def create_ticket_entry(complaint_row, issue_text):
    """
    Append a ticket row to tickets.csv and return ticket id and dict.
    """
    # Generate Ticket_ID (timestamp-based)
    ticket_id = f"T{int(time.time()*1000)}"
    created_at = datetime.now().isoformat(sep=' ', timespec='seconds')
    ticket = {
        "Ticket_ID": ticket_id,
        "Complaint_ID": complaint_row.get("Complaint_ID", ""),
        "Supplier": complaint_row.get("Supplier", ""),
        "Product": complaint_row.get("Product", ""),
        "Order_ID": complaint_row.get("Order_ID", ""),
        "Issue": issue_text,
        "Created_At": created_at,
        "Status": "Open",
        "Notes": ""
    }
    # Append to CSV
    with open(TICKETS_FILE, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            ticket["Ticket_ID"], ticket["Complaint_ID"], ticket["Supplier"], ticket["Product"],
            ticket["Order_ID"], ticket["Issue"], ticket["Created_At"], ticket["Status"], ticket["Notes"]
        ])
    return ticket

def send_slack_alert(ticket):
    """
    Send a simple Slack message using incoming webhook.
    """
    if not SLACK_WEBHOOK_URL:
        return False, "No SLACK_WEBHOOK_URL configured."

    text = (
        f":warning: *New Supplier Ticket Created*\n"
        f"*Ticket ID:* {ticket['Ticket_ID']}\n"
        f"*Supplier:* {ticket['Supplier']}\n"
        f"*Complaint ID:* {ticket['Complaint_ID']}\n"
        f"*Product:* {ticket['Product']}\n"
        f"*Issue:* {ticket['Issue']}\n"
        f"*Time:* {ticket['Created_At']}"
    )
    payload = {"text": text}
    try:
        resp = requests.post(SLACK_WEBHOOK_URL, json=payload, timeout=10)
        if resp.status_code == 200:
            return True, "Slack alert sent."
        else:
            return False, f"Slack returned {resp.status_code}: {resp.text}"
    except Exception as e:
        return False, str(e)

def send_email_alert(ticket, recipient):
    """
    Send basic email alert (optional). Requires SMTP config in .env
    """
    if not (SMTP_SERVER and EMAIL_USERNAME and EMAIL_PASSWORD):
        return False, "Email settings not configured."
    try:
        msg = MIMEMultipart()
        msg["From"] = EMAIL_USERNAME
        msg["To"] = recipient
        msg["Subject"] = f"[Meesho] New Supplier Ticket {ticket['Ticket_ID']}"
        body = (
            f"New Supplier Ticket Created\n\n"
            f"Ticket ID: {ticket['Ticket_ID']}\nSupplier: {ticket['Supplier']}\n"
            f"Complaint ID: {ticket['Complaint_ID']}\nProduct: {ticket['Product']}\n"
            f"Issue: {ticket['Issue']}\nCreated At: {ticket['Created_At']}\n"
        )
        msg.attach(MIMEText(body, "plain"))

        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        server.login(EMAIL_USERNAME, EMAIL_PASSWORD)
        server.sendmail(EMAIL_USERNAME, recipient, msg.as_string())
        server.quit()
        return True, "Email sent."
    except Exception as e:
        return False, str(e)

# ---------- UI ----------
st.sidebar.header("Settings")
auto_ticket_threshold = st.sidebar.number_input("Auto-ticket threshold per supplier (create ticket when supplier issues ≥ this in upload)", min_value=1, max_value=100, value=1)
slack_alerts = st.sidebar.checkbox("Send Slack alerts for every new ticket", value=True)
email_alerts = st.sidebar.checkbox("Send email alerts for every new ticket", value=False)
email_recipient = st.sidebar.text_input("Alert email recipient (if email alerts enabled)", value=EMAIL_USERNAME or "")

uploaded_file = st.file_uploader("Upload complaints CSV", type=["csv"])
if uploaded_file:
    df = pd.read_csv(uploaded_file)
    st.subheader("Uploaded complaints")
    st.dataframe(df)

    # Ensure required columns exist
    required_cols = {"Complaint_ID", "Message", "Supplier", "Product"}
    if not required_cols.issubset(set(df.columns)):
        st.error(f"Uploaded CSV must contain columns: {', '.join(required_cols)}")
    else:
        if st.button("Run AI classification & create tickets"):
            with st.spinner("Classifying complaints..."):
                df["AI_Category"] = df["Message"].apply(lambda t: call_openai_classify(str(t)))
            st.success("Classification complete")
            st.dataframe(df[["Complaint_ID", "Message", "Supplier", "AI_Category"]])

            # Count supplier issues per supplier
            supplier_counts = df[df["AI_Category"] == "Supplier Issue"]["Supplier"].value_counts()
            st.subheader("Supplier Issue Counts")
            st.table(supplier_counts.reset_index().rename(columns={"index": "Supplier", "Supplier": "Supplier_Issue_Count"}))

            # Create tickets for supplier issues (per complaint)
            new_tickets = []
            for _, row in df.iterrows():
                if row["AI_Category"] == "Supplier Issue":
                    ticket = create_ticket_entry(row, "Supplier Issue detected from complaint text")
                    new_tickets.append(ticket)
                    # Alerts
                    if slack_alerts:
                        ok, msg = send_slack_alert(ticket)
                        st.write(f"Slack: {msg}")
                    if email_alerts and USE_EMAIL_ALERTS and email_recipient:
                        ok, msg = send_email_alert(ticket, email_recipient)
                        st.write(f"Email: {msg}")

            # Additionally: create tickets for suppliers exceeding threshold in this upload
            for supplier, cnt in supplier_counts.items():
                if cnt >= auto_ticket_threshold:
                    # create a summary ticket for the supplier (if not already created for each complaint)
                    # For simplicity we'll create an aggregated ticket
                    sample_row = df[df["Supplier"] == supplier].iloc[0].to_dict()
                    ticket = create_ticket_entry(sample_row, f"Aggregate alert: {cnt} supplier issues in upload")
                    new_tickets.append(ticket)
                    if slack_alerts:
                        ok, msg = send_slack_alert(ticket)
                        st.write(f"Slack (aggregate): {msg}")
                    if email_alerts and USE_EMAIL_ALERTS and email_recipient:
                        ok, msg = send_email_alert(ticket, email_recipient)
                        st.write(f"Email (aggregate): {msg}")

            st.subheader("New Tickets Created")
            if new_tickets:
                st.write(f"{len(new_tickets)} ticket(s) created and logged to {TICKETS_FILE}.")
                st.dataframe(pd.DataFrame(new_tickets))
            else:
                st.write("No supplier-related tickets detected.")

# Show tickets CSV content
st.markdown("---")
st.subheader("All Tickets Log")
try:
    tickets_df = pd.read_csv(TICKETS_FILE)
    st.dataframe(tickets_df.sort_values("Created_At", ascending=False).head(200))
except Exception as e:
    st.write("No tickets yet or error reading tickets file:", e)
