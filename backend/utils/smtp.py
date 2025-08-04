from fastapi_mail import FastMail, MessageSchema, ConnectionConfig, MessageType
import os

from pydantic import SecretStr

# Email configuration for Outlook/Microsoft 365
conf = ConnectionConfig(
    MAIL_USERNAME=os.getenv("MAIL_USERNAME", ""),  # Your Outlook email address
    MAIL_PASSWORD=SecretStr(
        os.getenv("MAIL_PASSWORD", "")
    ),  # Your Outlook password or app password
    MAIL_FROM=os.getenv("MAIL_FROM", ""),  # Your Outlook email address
    MAIL_PORT=int(os.getenv("MAIL_PORT", 587)),
    MAIL_SERVER=os.getenv("MAIL_SERVER", "smtp.office365.com"),  # Outlook SMTP server
    MAIL_STARTTLS=True,
    MAIL_SSL_TLS=False,
    USE_CREDENTIALS=True,
    VALIDATE_CERTS=False,  # Disable certificate validation for testing
    TEMPLATE_FOLDER=None,
)

fastmail = FastMail(conf)


async def send_email(subject: str, body: str, to: list[str], cc: list[str]):
    message = MessageSchema(
        subject=subject,
        recipients=to,
        body=body,
        subtype=MessageType.plain,
        cc=cc,
    )
    await fastmail.send_message(message)
