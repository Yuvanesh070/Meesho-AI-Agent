import smtplib
from email.mime.text import MIMEText
import streamlit as st

# Read Gmail credentials from Streamlit Secrets
EMAIL_USER = st.secrets["EMAIL_USER"]
EMAIL_PASS = st.secrets["EMAIL_PASS"]

def send_email_alert(to_email, supplier_name, issue_count):
    subject = f"⚠️ Supplier Alert: {supplier_name} exceeded issue threshold"
    body = f"""
    Hi Team,

    The supplier **{supplier_name}** has reported **{issue_count} issues** in the latest upload.

    Please review the supplier performance and take necessary action.

    Regards,
    Meesho Supplier Quality AI Agent
    """

    msg = MIMEText(body, "plain")
    msg["Subject"] = subject
    msg["From"] = EMAIL_USER
    msg["To"] = to_email

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(EMAIL_USER, EMAIL_PASS)
            server.send_message(msg)
        st.success(f"✅ Email sent to {to_email} for supplier {supplier_name}")
    except Exception as e:
        st.error(f"❌ Error sending email: {e}")
