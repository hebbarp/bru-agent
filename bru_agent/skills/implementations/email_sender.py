"""
Email Sender Skill - Sends emails via SMTP.
"""

import smtplib
import ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from pathlib import Path
from typing import Any, Dict, List, Optional
from loguru import logger

from ..base import BaseSkill


class EmailSenderSkill(BaseSkill):
    """Skill for sending emails via SMTP."""

    name = "send_email"
    description = "Send an email to one or more recipients. Use this when asked to send, email, or mail something to someone."
    version = "1.0.0"

    def __init__(self, config: dict = None):
        super().__init__(config)
        self.smtp_server = None
        self.smtp_port = 587
        self.email_address = None
        self.email_password = None
        self.use_tls = True

        if config:
            email_config = config.get('email', {})
            self.smtp_server = email_config.get('smtp_server')
            self.smtp_port = email_config.get('smtp_port', 587)
            self.email_address = email_config.get('email_address')
            self.email_password = email_config.get('password')
            self.use_tls = email_config.get('use_tls', True)

    def get_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "to": {
                    "type": "string",
                    "description": "Recipient email address(es). Multiple addresses can be comma-separated."
                },
                "subject": {
                    "type": "string",
                    "description": "Email subject line"
                },
                "body": {
                    "type": "string",
                    "description": "Email body content (plain text or HTML)"
                },
                "cc": {
                    "type": "string",
                    "description": "Optional CC recipients (comma-separated)"
                },
                "is_html": {
                    "type": "boolean",
                    "description": "Whether the body is HTML formatted. Default is false (plain text)."
                },
                "attachment_path": {
                    "type": "string",
                    "description": "Optional path to a file to attach"
                }
            },
            "required": ["to", "subject", "body"]
        }

    async def execute(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Send an email."""
        to_addresses = params.get('to', '')
        subject = params.get('subject', '')
        body = params.get('body', '')
        cc = params.get('cc', '')
        is_html = params.get('is_html', False)
        attachment_path = params.get('attachment_path')

        # Validate configuration
        if not self.smtp_server or not self.email_address or not self.email_password:
            return {
                "success": False,
                "error": "Email not configured. Please set SMTP server, email address, and password in config."
            }

        if not to_addresses:
            return {"success": False, "error": "No recipient specified"}

        if not subject:
            return {"success": False, "error": "No subject specified"}

        # Parse recipients
        to_list = [addr.strip() for addr in to_addresses.split(',') if addr.strip()]
        cc_list = [addr.strip() for addr in cc.split(',') if addr.strip()] if cc else []

        try:
            # Create message
            msg = MIMEMultipart('alternative')
            msg['From'] = self.email_address
            msg['To'] = ', '.join(to_list)
            msg['Subject'] = subject

            if cc_list:
                msg['Cc'] = ', '.join(cc_list)

            # Add body
            if is_html:
                msg.attach(MIMEText(body, 'html'))
            else:
                msg.attach(MIMEText(body, 'plain'))

            # Add attachment if specified
            if attachment_path:
                attachment_result = self._add_attachment(msg, attachment_path)
                if not attachment_result['success']:
                    return attachment_result

            # Send email
            all_recipients = to_list + cc_list

            context = ssl.create_default_context()

            with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
                if self.use_tls:
                    server.starttls(context=context)
                server.login(self.email_address, self.email_password)
                server.sendmail(self.email_address, all_recipients, msg.as_string())

            logger.info(f"Email sent to {to_addresses}")

            return {
                "success": True,
                "result": {
                    "message": f"Email sent successfully to {', '.join(to_list)}",
                    "recipients": to_list,
                    "cc": cc_list,
                    "subject": subject,
                    "has_attachment": attachment_path is not None
                }
            }

        except smtplib.SMTPAuthenticationError as e:
            logger.error(f"SMTP authentication failed: {e}")
            return {"success": False, "error": "Email authentication failed. Check credentials."}
        except smtplib.SMTPException as e:
            logger.error(f"SMTP error: {e}")
            return {"success": False, "error": f"Failed to send email: {str(e)}"}
        except Exception as e:
            logger.error(f"Email error: {e}")
            return {"success": False, "error": f"Failed to send email: {str(e)}"}

    def _add_attachment(self, msg: MIMEMultipart, filepath: str) -> Dict[str, Any]:
        """Add an attachment to the email."""
        path = Path(filepath)

        if not path.exists():
            return {"success": False, "error": f"Attachment not found: {filepath}"}

        try:
            with open(path, 'rb') as f:
                part = MIMEBase('application', 'octet-stream')
                part.set_payload(f.read())

            encoders.encode_base64(part)
            part.add_header(
                'Content-Disposition',
                f'attachment; filename="{path.name}"'
            )
            msg.attach(part)

            return {"success": True}

        except Exception as e:
            return {"success": False, "error": f"Failed to attach file: {str(e)}"}
