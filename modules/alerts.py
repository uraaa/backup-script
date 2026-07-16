import logging
import smtplib
import ssl
from email.mime.text import MIMEText
from typing import List

import requests

logger = logging.getLogger(__name__)


def send_error_email(smtp_host: str, smtp_port: int, use_tls: bool, username: str, password: str,
                     from_email: str, to_emails: List[str], subject: str, body: str) -> None:
    msg = MIMEText(body, _charset='utf-8')
    msg['Subject'] = subject
    msg['From'] = from_email
    msg['To'] = ', '.join(to_emails)

    if use_tls:
        context = ssl.create_default_context()
        with smtplib.SMTP(smtp_host, smtp_port, timeout=60) as server:
            server.ehlo()
            server.starttls(context=context)
            server.ehlo()
            if username:
                server.login(username, password)
            server.sendmail(from_email, to_emails, msg.as_string())
    else:
        with smtplib.SMTP(smtp_host, smtp_port, timeout=60) as server:
            if username:
                server.login(username, password)
            server.sendmail(from_email, to_emails, msg.as_string())

    logger.info("Alert email sent: %s -> %s", from_email, to_emails)


def send_telegram_message(bot_token: str, chat_id: str, text: str) -> None:
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    # Telegram messages are capped at 4096 chars; truncate long tracebacks.
    if len(text) > 4000:
        text = text[:4000] + "\n... (truncated)"
    resp = requests.post(url, data={"chat_id": chat_id, "text": text}, timeout=30)
    if resp.status_code != 200:
        logger.error("Failed to send Telegram alert: %s %s", resp.status_code, resp.text)
        raise RuntimeError(f"Telegram sendMessage failed: {resp.status_code} {resp.text}")
    logger.info("Alert sent via Telegram to chat_id=%s", chat_id)
