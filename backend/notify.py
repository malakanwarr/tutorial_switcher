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

      # Dynamic section based on Pivot role
        if match['swap_type'] == "standard":
            whatsapp_section = f"""
            <p style="font-size: 16px;"><strong>Your Match's WhatsApp:</strong> <a href="https://wa.me/{match['partner_whatsapp'].replace('+', '')}" style="color: #6366f1; text-decoration: none; font-weight: bold;">{match['partner_whatsapp']}</a></p>
            <p style="font-size: 14px; color: #4b5563; margin-top: 15px;"><strong>IMPORTANT:</strong> Message your partner on WhatsApp to confirm the swap on the university portal.</p>
            """
        elif match['swap_type'] == "double-switch":
            whatsapp_section = f"""
            <div style="background: #fffbeb; border-left: 4px solid #f59e0b; padding: 15px; margin: 20px 0;">
                <p style="margin-top: 0; font-size: 15px; font-weight: bold; color: #b45309;">🔄 Double Switch Required!</p>
                <p style="font-size: 14px; color: #b45309;">You are the bridge! You must do two quick swaps. <strong>Create a WhatsApp group with both students below to coordinate the order before dropping anything!</strong></p>
                <ol style="font-size: 14px; color: #b45309; padding-left: 20px; line-height: 1.5;">
                    <li><strong>Step 1:</strong> Swap Tutorial {match['my_slot']} for Tutorial {match['step1_slot']} with:<br><a href="https://wa.me/{match['step1_whatsapp'].replace('+', '')}" style="font-weight: bold; color: #b45309;">{match['step1_whatsapp']}</a></li>
                    <li style="margin-top: 10px;"><strong>Step 2:</strong> Swap Tutorial {match['step1_slot']} for your goal Tutorial {match['partner_slot']} with:<br><a href="https://wa.me/{match['step2_whatsapp'].replace('+', '')}" style="font-weight: bold; color: #b45309;">{match['step2_whatsapp']}</a></li>
                </ol>
                <p style="font-size: 14px; color: #b45309; margin-bottom: 0;"><strong>⚠️ IMPORTANT:</strong> Message your partners on WhatsApp to confirm the swaps on the university portal.</p>
            </div>
            """

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
                
                {whatsapp_section}
                
                <div style="background-color: #fee2e2; border: 1px solid #ef4444; padding: 15px; border-radius: 8px; margin-top: 25px; text-align: center;">
                  <p style="font-size: 15px; color: #b91c1c; font-weight: bold; margin-top: 0;">🛑 REQUIRED: UPDATE YOUR STATUS</p>
                  <p style="font-size: 13px; color: #991b1b; margin-bottom: 15px;">If you do not click one of these buttons after trying to swap, you will be stuck in the system and cannot match again.</p>
                  <a href="https://tutorial-switcher.vercel.app/confirm-swap?token={match['token']}" style="background-color: #4ade80; color: white; padding: 14px 20px; text-decoration: none; border-radius: 8px; font-weight: bold; display: inline-block; margin-bottom: 10px; width: 85%; box-sizing: border-box;">✅ Swap Successful (Done)</a>
                  <br>
                  <a href="https://tutorial-switcher.vercel.app/flake-swap?token={match['token']}" style="background-color: #f87171; color: white; padding: 14px 20px; text-decoration: none; border-radius: 8px; font-weight: bold; display: inline-block; width: 85%; box-sizing: border-box;">❌ Partner Flaked (Cancel Match)</a>
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

        time.sleep(5)

    server.quit()
    print("All match notifications sent successfully!")