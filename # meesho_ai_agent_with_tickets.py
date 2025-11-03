# meesho_ai_agent_with_tickets.py

import streamlit as st
import pandas as pd
import os
import time
import requests
import csv
from datetime import datetime
from dotenv import load_dotenv
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# ---------- Load config ----------
load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL")
SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
EMAIL_USERNAME = os.getenv("EMAIL_USERNAME")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
USE_EMAIL_ALERTS = os.getenv("USE_EMAIL_ALERTS", "false").lower() == "true"

# Debug info
print("Loaded config:")
print("SMTP_SERVER:", SMTP_SERVER)
print("EMAIL_USERNAME:", EMAIL_USERNAME)
print("USE_EMAIL_ALERTS:", USE_EMAIL_ALERTS)

if not OPENAI_API_KEY:
    st.error("Please set OPENAI_API_KEY in your .env or Streamlit secrets.")
    st.stop()

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

# ---------- Dummy Classification Function ----------
# (OpenAI disabled in your setup, using fixed logic)
def call_openai_classify(text):
    text = text.lower()
    if "damage" in text or "wrong" in text or "missing" in text or "color" in text:
        return "Supplier Issue"
    elif "late" in text or "courier" in text or "delivery" in text:
        return "Logistics Issue"
    else:
        return "Customer Issue"

# ---------- Ticket Creation ----------
def create_ticket_entry(complaint_row, issue_text):
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
    with open(TICKETS_FILE, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(ticket.values())
    return ticket

# ---------- Email Alert ----------
def send_email_alert(ticket, recipient):
    if not (SMTP_SERVER and EMAIL_USERNAME and EMAIL_PASSWORD):
        print("Email not configured properly")
        return False, "Email settings not configured."

    try:
        print("Attempting to send mail to:", recipient)
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
        print("✅ Email successfully sent to", recipient)
        return True, "Email sent successfully."
    except Exception as e:
        print("❌ Email failed:", e)
        return False, str(e)

# ---------- UI ----------
st.sidebar.header("Settings")
auto_ticket_threshold = st.sidebar.number_input(
    "Auto-ticket threshold per supplier (create ticket when supplier issues ≥ this in upload)",
    min_value=1, max_value=100, value=3
)
email_alerts = st.sidebar.checkbox("Send email alerts for every new ticket", value=True)
email_recipient = st.sidebar.text_input("Alert email recipient", value="yuvaneshbabu007@gmail.com")

uploaded_file = st.file_uploader("Upload complaints CSV", type=["csv"])
if uploaded_file:
    df = pd.read_csv(uploaded_file)
    st.subheader("Uploaded complaints")
    st.dataframe(df)

    if st.button("Run AI classification & create tickets"):
        with st.spinner("Classifying complaints..."):
            df["AI_Category"] = df["Message"].apply(call_openai_classify)
        st.success("Classification complete")
        st.dataframe(df[["Complaint_ID", "Message", "Supplier", "AI_Category"]])

        supplier_counts = df[df["AI_Category"] == "Supplier Issue"]["Supplier"].value_counts()
        st.subheader("Supplier Issue Counts")
        st.table(supplier_counts.reset_index().rename(columns={"index": "Supplier", "Supplier": "Supplier_Issue_Count"}))

        new_tickets = []
        for _, row in df.iterrows():
            if row["AI_Category"] == "Supplier Issue":
                ticket = create_ticket_entry(row, "Supplier Issue detected from complaint text")
                new_tickets.append(ticket)
                if email_alerts and USE_EMAIL_ALERTS:
                    send_email_alert(ticket, email_recipient)

        for supplier, cnt in supplier_counts.items():
            if cnt >= auto_ticket_threshold:
                sample_row = df[df["Supplier"] == supplier].iloc[0].to_dict()
                ticket = create_ticket_entry(sample_row, f"Aggregate alert: {cnt} supplier issues in upload")
                new_tickets.append(ticket)
                if email_alerts and USE_EMAIL_ALERTS:
                    send_email_alert(ticket, email_recipient)

        st.subheader("New Tickets Created")
        if new_tickets:
            st.write(f"{len(new_tickets)} ticket(s) created and logged to {TICKETS_FILE}.")
            st.dataframe(pd.DataFrame(new_tickets))
        else:
            st.write("No supplier-related tickets detected.")

st.markdown("---")
st.subheader("All Tickets Log")
try:
    tickets_df = pd.read_csv(TICKETS_FILE)
    st.dataframe(tickets_df.sort_values("Created_At", ascending=False).head(200))
except Exception as e:
    st.write("No tickets yet or error reading tickets file:", e)
