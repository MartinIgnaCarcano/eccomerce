from flask_mail import Message
from flask import current_app
from extension import mail
def send_email(to: str, subject: str, html: str, cc=None, bcc=None,reply_to=None):
    msg = Message(
        subject=subject,
        recipients=[to],
        html=html,
        cc=cc or [],
        bcc=bcc or [],
        sender=current_app.config.get("MAIL_DEFAULT_SENDER"),
        reply_to=reply_to,
    )
    mail.send(msg)