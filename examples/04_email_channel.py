"""
Example 4: Email Channel
Configure BRU to monitor an email inbox and respond to messages.

BRU will:
1. Connect to your IMAP server
2. Poll for new unread emails from authorized senders
3. Process each email through Claude
4. Send a reply via SMTP

Setup:
1. Copy .env.example to .env and fill in email credentials
2. Edit authorized_senders.yaml to whitelist senders
3. Run this script

For Gmail: use an App Password (not your regular password)
  - Go to myaccount.google.com > Security > 2-Step Verification > App passwords
  - Generate one for "Mail"
"""

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from bru_agent.mail_client.client import EmailClient


async def main():
    # Check config
    email = os.getenv('BRU_EMAIL_ADDRESS')
    password = os.getenv('BRU_EMAIL_PASSWORD')
    imap = os.getenv('BRU_IMAP_SERVER')

    if not all([email, password, imap]):
        print("Set these in .env:")
        print("  BRU_EMAIL_ADDRESS=your@gmail.com")
        print("  BRU_EMAIL_PASSWORD=your-app-password")
        print("  BRU_IMAP_SERVER=imap.gmail.com")
        print("  BRU_SMTP_SERVER=smtp.gmail.com")
        return

    # Authorized senders — only emails from these people get processed
    authorized_senders = [
        {"email": "boss@company.com", "name": "Boss"},
        # Add more as needed
    ]
    authorized_domains = [
        # "company.com",  # All emails from this domain
    ]

    print(f"Email: {email}")
    print(f"IMAP: {imap}")
    print(f"Authorized: {len(authorized_senders)} senders, {len(authorized_domains)} domains")

    # Connect
    client = EmailClient(
        config={
            'imap_server': imap,
            'imap_port': int(os.getenv('BRU_IMAP_PORT', 993)),
            'smtp_server': os.getenv('BRU_SMTP_SERVER', 'smtp.gmail.com'),
            'smtp_port': int(os.getenv('BRU_SMTP_PORT', 587)),
            'email_address': email,
            'password': password,
        },
        authorized_senders=authorized_senders,
        authorized_domains=authorized_domains,
    )

    connected = await client.connect()
    if not connected:
        print("Failed to connect to IMAP server")
        return

    print("Connected. Checking for new emails...\n")

    # Poll once
    emails = await client.get_new_emails()

    if not emails:
        print("No new emails from authorized senders.")
    else:
        for email_msg in emails:
            print(f"From: {email_msg['sender']}")
            print(f"Subject: {email_msg['subject']}")
            print(f"Body preview: {email_msg['body'][:200]}...")
            print()

            # In a real setup, you'd pass this to Claude and send a reply:
            # response = await execute_with_claude(email_msg['body'])
            # await client.send_email(email_msg['sender'], f"Re: {email_msg['subject']}", response)

    await client.close()
    print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
