"""
Email Client - IMAP/SMTP integration for email handling.
"""

import imaplib
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.parser import Parser
from email.header import decode_header
from typing import List, Dict, Optional
from loguru import logger


class EmailClient:
    """Client for email operations via IMAP/SMTP."""

    def __init__(self, config: dict, authorized_senders: List[dict], authorized_domains: List[str]):
        self.config = config
        self.authorized_senders = {s['email'].lower(): s for s in authorized_senders}
        self.authorized_domains = [d.lower() for d in authorized_domains]

        self.imap_server = config.get('imap_server')
        self.smtp_server = config.get('smtp_server')
        self.email_address = config.get('email_address')
        self.password = config.get('password')

        self.imap = None
        self.smtp = None

    async def connect(self) -> bool:
        """Connect to email servers.

        Returns:
            True if connected successfully
        """
        try:
            # IMAP connection
            self.imap = imaplib.IMAP4_SSL(
                self.imap_server,
                self.config.get('imap_port', 993)
            )
            self.imap.login(self.email_address, self.password)
            logger.info("Connected to IMAP server")
            return True

        except Exception as e:
            logger.error(f"Failed to connect to email: {e}")
            return False

    def _is_authorized(self, sender_email: str) -> bool:
        """Check if sender is authorized.

        Args:
            sender_email: The sender's email address

        Returns:
            True if authorized
        """
        sender_lower = sender_email.lower()

        # Check exact match
        if sender_lower in self.authorized_senders:
            return True

        # Check domain
        domain = sender_lower.split('@')[-1] if '@' in sender_lower else ''
        if domain in self.authorized_domains:
            return True

        return False

    async def get_new_emails(self, folder: str = "INBOX") -> List[Dict]:
        """Fetch new unread emails from authorized senders.

        Args:
            folder: Mail folder to check

        Returns:
            List of email dictionaries
        """
        if not self.imap:
            return []

        emails = []

        try:
            self.imap.select(folder)

            # Search for unread emails
            _, message_numbers = self.imap.search(None, "UNSEEN")

            for num in message_numbers[0].split():
                _, msg_data = self.imap.fetch(num, "(RFC822)")

                for response_part in msg_data:
                    if isinstance(response_part, tuple):
                        parser = Parser()
                        msg = parser.parsestr(response_part[1].decode('utf-8', errors='ignore'))

                        # Extract sender
                        sender = msg.get('From', '')
                        sender_email = self._extract_email(sender)

                        # Check authorization
                        if not self._is_authorized(sender_email):
                            continue

                        # Extract subject
                        subject = msg.get('Subject', '')
                        if subject:
                            decoded = decode_header(subject)
                            subject = decoded[0][0]
                            if isinstance(subject, bytes):
                                subject = subject.decode('utf-8', errors='ignore')

                        # Extract body
                        body = self._get_body(msg)

                        emails.append({
                            'id': num.decode(),
                            'sender': sender_email,
                            'sender_full': sender,
                            'subject': subject,
                            'body': body,
                            'date': msg.get('Date', '')
                        })

        except Exception as e:
            logger.error(f"Failed to fetch emails: {e}")

        return emails

    def _extract_email(self, sender: str) -> str:
        """Extract email address from sender string."""
        if '<' in sender and '>' in sender:
            return sender.split('<')[1].split('>')[0]
        return sender

    def _get_body(self, msg) -> str:
        """Extract body text from email message."""
        body = ""

        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                if content_type == "text/plain":
                    body = part.get_payload(decode=True).decode('utf-8', errors='ignore')
                    break
        else:
            body = msg.get_payload(decode=True).decode('utf-8', errors='ignore')

        return body

    async def send_email(self, to: str, subject: str, body: str, reply_to_id: Optional[str] = None) -> bool:
        """Send an email.

        Args:
            to: Recipient email address
            subject: Email subject
            body: Email body
            reply_to_id: Optional message ID to reply to

        Returns:
            True if sent successfully
        """
        try:
            msg = MIMEMultipart()
            msg['From'] = self.email_address
            msg['To'] = to
            msg['Subject'] = subject

            if reply_to_id:
                msg['In-Reply-To'] = reply_to_id
                msg['References'] = reply_to_id

            msg.attach(MIMEText(body, 'plain'))

            with smtplib.SMTP(self.smtp_server, self.config.get('smtp_port', 587)) as smtp:
                smtp.starttls()
                smtp.login(self.email_address, self.password)
                smtp.send_message(msg)

            logger.info(f"Email sent to {to}")
            return True

        except Exception as e:
            logger.error(f"Failed to send email: {e}")
            return False

    async def close(self):
        """Close email connections."""
        if self.imap:
            try:
                self.imap.logout()
            except:
                pass
            self.imap = None
