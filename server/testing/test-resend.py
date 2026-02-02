from datetime import datetime
import resend
from typing import Optional

resend.api_key = "re_64z2BNNJ_CWmVLsEd5ZCBD5VqgTxpwouo"

def generate_verification_email(user_name: str, otp_code: str, login_url: str, icon_url: Optional[str] = None) -> str:
    """
    Generate a beautiful verification email with wavy gradient design.
    
    Args:
        user_name: Recipient's name
        otp_code: One-time password code
        login_url: URL for verification button
        icon_url: Full URL to the icon image (must be publicly accessible)
    
    Returns:
        HTML string for the email
    """
    year = datetime.now().year
    
    # Use provided icon URL or fallback to emoji
    logo_html = f'<img src="{icon_url}" alt="Spark AI" class="logo-icon">' if icon_url else '✦'
    
    html = f"""
<!DOCTYPE html>
<html>
<head>
<style>
body {{
    margin: 0;
    padding: 0;
    background: linear-gradient(135deg, #f0f9ff 0%, #e0f2fe 100%);
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Helvetica Neue', Arial, sans-serif;
}}

.wrapper {{
    width: 100%;
    padding: 30px 20px;
    background: linear-gradient(135deg, #f0f9ff 0%, #e0f2fe 100%);
}}

.card {{
    max-width: 580px;
    margin: 0 auto;
    background: #ffffff;
    border-radius: 16px;
    overflow: hidden;
    box-shadow: 0 20px 60px rgba(59, 130, 246, 0.08);
    border: 1px solid rgba(147, 197, 253, 0.15);
}}

.wave-header {{
    position: relative;
    height: 110px;
    background: linear-gradient(135deg, #dbeafe 0%, #bfdbfe 50%, #93c5fd 100%);
    overflow: hidden;
}}

.wave-header::before {{
    content: '';
    position: absolute;
    bottom: 0;
    left: 0;
    width: 100%;
    height: 100%;
    background: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 1200 120'%3E%3Cpath fill='%23ffffff' d='M0,64 C240,96 480,32 720,64 C960,96 1200,32 1200,32 L1200,120 L0,120 Z'/%3E%3C/svg%3E") no-repeat bottom;
    background-size: cover;
}}

.logo {{
    padding: 24px 0 0 32px;
    font-size: 24px;
    font-weight: 700;
    color: #1e3a8a;
    letter-spacing: -0.5px;
    position: relative;
    z-index: 1;
    display: flex;
    align-items: center;
    gap: 10px;
}}

.logo-icon {{
    width: 32px;
    height: 32px;
}}

.content {{
    padding: 24px 32px 28px;
    color: #1e293b;
}}

.greeting {{
    font-size: 16px;
    color: #475569;
    margin-bottom: 14px;
    line-height: 1.5;
}}

.greeting strong {{
    color: #1e3a8a;
    font-weight: 600;
}}

.message {{
    font-size: 14px;
    color: #64748b;
    line-height: 1.6;
    margin-bottom: 20px;
}}

.otp-container {{
    margin: 20px 0;
    padding: 18px;
    background: linear-gradient(135deg, #eff6ff 0%, #dbeafe 100%);
    border: 2px dashed #93c5fd;
    border-radius: 12px;
    text-align: center;
}}

.otp-label {{
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 1px;
    color: #60a5fa;
    font-weight: 600;
    margin-bottom: 8px;
}}

.otp {{
    font-size: 30px;
    font-weight: 700;
    letter-spacing: 8px;
    color: #1e40af;
    font-family: 'Courier New', monospace;
}}

.button {{
    display: inline-block;
    background: linear-gradient(135deg, #3b82f6 0%, #2563eb 100%);
    color: #ffffff;
    text-align: center;
    padding: 13px 32px;
    border-radius: 10px;
    text-decoration: none;
    font-weight: 600;
    font-size: 14px;
    box-shadow: 0 4px 12px rgba(59, 130, 246, 0.2);
}}

.security-note {{
    margin-top: 20px;
    padding: 14px;
    background: #f8fafc;
    border-left: 3px solid #93c5fd;
    border-radius: 8px;
    font-size: 13px;
    color: #64748b;
    line-height: 1.5;
}}

.wave-footer {{
    position: relative;
    height: 70px;
    background: linear-gradient(135deg, #ffffff 0%, #f0f9ff 100%);
    overflow: hidden;
}}

.wave-footer::before {{
    content: '';
    position: absolute;
    top: 0;
    left: 0;
    width: 100%;
    height: 100%;
    background: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 1200 120'%3E%3Cpath fill='%23ffffff' d='M0,64 C240,32 480,96 720,64 C960,32 1200,96 1200,96 L1200,0 L0,0 Z'/%3E%3C/svg%3E") no-repeat top;
    background-size: cover;
}}

.footer {{
    text-align: center;
    padding: 20px 32px;
    background: #f8fafc;
    font-size: 12px;
    color: #94a3b8;
    border-top: 1px solid #e0f2fe;
}}

.footer-text {{
    margin: 4px 0;
}}

.divider {{
    display: inline-block;
    margin: 0 8px;
    color: #cbd5e1;
}}
</style>
</head>

<body>
<div class="wrapper">
    <div class="card">

        <div class="wave-header">
            <div class="logo">
                {logo_html}
                Spark AI
            </div>
        </div>

        <div class="content">
            <div class="greeting">
                Hello <strong>{user_name}</strong>,
            </div>

            <div class="message">
                Welcome back to Spark AI. Please verify your identity using the code below to continue securely.
            </div>

            <div class="otp-container">
                <div class="otp-label">Verification Code</div>
                <div class="otp">{otp_code}</div>
            </div>

            <div style="text-align: center; margin: 20px 0;">
                <a href="{login_url}" class="button">Verify & Continue</a>
            </div>

            <div class="security-note">
                <strong>Security Notice:</strong> This code expires shortly. If you didn't request this, please ignore this message. Never share this code with anyone.
            </div>
        </div>

        <div class="wave-footer"></div>

        <div class="footer">
            <div class="footer-text">© {year} Spark AI. All rights reserved.</div>
            <div class="footer-text">
                Trusted AI Platform <span class="divider">•</span> Secure Authentication
            </div>
        </div>

    </div>
</div>
</body>
</html>
"""
    return html


# Usage example
def send_verification_email(to_email: str, user_name: str, otp_code: str, login_url: str = "https://spark.ai/login", icon_url: Optional[str] = None):
    """
    Send a verification email to the specified address.
    
    Args:
        to_email: Recipient's email address
        user_name: Recipient's name
        otp_code: One-time password code
        login_url: URL for verification (optional)
        icon_url: Full URL to the icon image (optional, must be publicly accessible)
    
    Returns:
        Response from Resend API
    """
    html_content = generate_verification_email(user_name, otp_code, login_url, icon_url)
    
    params = {
        "from": "Spark AI <no-reply@siddhantyadav.com.np>",
        "to": [to_email],
        "subject": "Your Spark AI Verification Code",
        "html": html_content,
    }
    
    return resend.Emails.send(params) #type: ignore


# Example usage
if __name__ == "__main__":
    response = send_verification_email(
        to_email="siddthecoder@gmail.com",
        user_name="Sidd",
        otp_code="829301",
        icon_url="https://res.cloudinary.com/dlrtkxkpg/image/upload/fl_preserve_transparency/v1764587833/icon-high-ql_srhpo8.jpg?_s=public-apps"  # Must be a full public URL
    )
    print(response)