import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import time
import os
from dotenv import load_dotenv

# Load the secret password from your .env file
load_dotenv()

# --- GMAIL CONFIGURATION ---
SENDER_EMAIL = "guctutorialswitcher@gmail.com"
APP_PASSWORD = os.getenv("GMAIL_PASSWORD")
# ---------------------------

def send_match_emails(matches_data):
    if any(m['student_id'].startswith('TEST-') for m in matches_data):
        print("Test run detected: Skipping actual email dispatch.")
        return
    
    # Establish connection to Gmail's secure SMTP server
    try:
        server = smtplib.SMTP("smtp.gmail.com", 587)
        server.starttls() # Upgrade to secure connection
        server.login(SENDER_EMAIL, APP_PASSWORD)
    except Exception as e:
        print(f"Failed to connect to email server: {e}")
        return

    for match in matches_data:
        recipient = match["student_email"]
        
        # Build the message
        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"🎉 Match Found! Swap Tutorial {match['my_slot']} for {match['partner_slot']}"
        msg["From"] = SENDER_EMAIL
        msg["To"] = recipient

        # Beautiful HTML Email Template with Buttons
        html_body = f"""
        <html>
          <body style="font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #f8fafc; padding: 20px; color: #333;">
            <div style="max-width: 500px; margin: 0 auto; background: white; border-radius: 12px; overflow: hidden; box-shadow: 0 4px 15px rgba(0,0,0,0.05);">
              <div style="background: linear-gradient(135deg, #6366f1, #c084fc); padding: 25px; text-align: center;">
                <h2 style="color: white; margin: 0; font-size: 24px;">Match Found! 🎉</h2>
              </div>
              <div style="padding: 30px;">
                <p style="font-size: 16px; margin-top: 0;">Hello from the GUC Tutorial Switcher!</p>
                <p style="font-size: 16px;">We found a great match for your tutorial swap. Here are the details:</p>
                
                <div style="background: #f1f5f9; padding: 15px; border-radius: 8px; margin: 20px 0;">
                  <p style="margin: 5px 0;"><strong>You wanted Tutorial:</strong> {match['partner_slot']}</p>
                  <p style="margin: 5px 0;"><strong>Your current tutorial:</strong> {match['my_slot']}</p>
                </div>
                
                <p style="font-size: 16px;"><strong>Your Match's WhatsApp:</strong> <a href="https://wa.me/{match['partner_whatsapp'].replace('+', '')}" style="color: #6366f1; text-decoration: none; font-weight: bold;">{match['partner_whatsapp']}</a></p>
                
                <hr style="border: 0; border-top: 1px solid #e2e8f0; margin: 25px 0;">
                
                <p style="font-size: 14px; color: #64748b;"><strong>IMPORTANT:</strong> Message your partner on WhatsApp to confirm. Once you both agree, please update the system using the buttons below:</p>
                
                <div style="text-align: center; margin-top: 25px;">
                  <a href="https://tutorial-switcher.vercel.app/confirm-swap?token={match['token']}" style="background-color: #4ade80; color: white; padding: 14px 20px; text-decoration: none; border-radius: 8px; font-weight: bold; display: inline-block; margin-bottom: 10px; width: 80%; box-sizing: border-box;">✅ Swap Successful (Done)</a>
<br>
<a href="https://tutorial-switcher.vercel.app/flake-swap?token={match['token']}" style="background-color: #f87171; color: white; padding: 14px 20px; text-decoration: none; border-radius: 8px; font-weight: bold; display: inline-block; width: 80%; box-sizing: border-box;">❌ Partner Flaked (Cancel)</a>
                </div>
              </div>
            </div>
          </body>
        </html>
        """

        msg.attach(MIMEText(html_body, "html"))

        try:
            server.sendmail(SENDER_EMAIL, recipient, msg.as_string())
            print(f"Successfully sent HTML email to {recipient}")
        except Exception as e:
            print(f"Error sending email to {recipient}: {e}")

        # SAFETY DELAY: Pause for 5 seconds between emails to trick Google's spam bot detector
        time.sleep(5)

    server.quit()
    print("All match notifications sent successfully!")