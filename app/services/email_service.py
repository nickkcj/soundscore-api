import resend
from typing import Optional

from app.config import get_settings

settings = get_settings()


class EmailService:
    """Service for sending emails using Resend."""

    def __init__(self):
        if settings.resend_api_key:
            resend.api_key = settings.resend_api_key

    @staticmethod
    def _get_password_reset_email_html(reset_url: str) -> str:
        """Generate styled HTML email template for password reset."""
        return f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Redefinir sua senha - SoundScore</title>
</head>
<body style="margin: 0; padding: 0; font-family: Arial, Helvetica, sans-serif; background-color: #f3f4f6;">
    <!-- Preheader text (shows in email preview) -->
    <div style="display: none; max-height: 0; overflow: hidden;">
        Clique para redefinir sua senha do SoundScore. Este link expira em 15 minutos.
    </div>

    <table role="presentation" cellspacing="0" cellpadding="0" border="0" width="100%" style="background-color: #f3f4f6;">
        <tr>
            <td style="padding: 40px 20px;">
                <table role="presentation" cellspacing="0" cellpadding="0" border="0" width="600" style="max-width: 600px; margin: 0 auto; background-color: #ffffff;">
                    <!-- Header rosa com logo -->
                    <tr>
                        <td style="background-color: #C9184A; padding: 32px 40px; text-align: center;">
                            <h1 style="margin: 0; color: #ffffff; font-size: 28px; font-weight: bold; letter-spacing: 1px;">SOUNDSCORE</h1>
                            <p style="margin: 8px 0 0 0; color: #fecdd3; font-size: 13px;">Rank your taste in music</p>
                        </td>
                    </tr>

                    <!-- Content -->
                    <tr>
                        <td style="padding: 32px 40px;">
                            <h2 style="margin: 0 0 16px 0; color: #111827; font-size: 22px; font-weight: bold;">Redefinir sua senha</h2>
                            <p style="margin: 0 0 24px 0; color: #4b5563; font-size: 15px; line-height: 1.6;">
                                Recebemos uma solicitação para redefinir sua senha. Clique no botão abaixo para criar uma nova senha. Este link expira em <strong>15 minutos</strong>.
                            </p>

                            <!-- Button rosa -->
                            <table role="presentation" cellspacing="0" cellpadding="0" border="0" width="100%">
                                <tr>
                                    <td align="center" style="padding: 8px 0 24px 0;">
                                        <!--[if mso]>
                                        <v:roundrect xmlns:v="urn:schemas-microsoft-com:vml" xmlns:w="urn:schemas-microsoft-com:office:word" href="{reset_url}" style="height:48px;v-text-anchor:middle;width:200px;" arcsize="10%" strokecolor="#C9184A" fillcolor="#C9184A">
                                        <w:anchorlock/>
                                        <center style="color:#ffffff;font-family:Arial,sans-serif;font-size:16px;font-weight:bold;">Clique Aqui</center>
                                        </v:roundrect>
                                        <![endif]-->
                                        <!--[if !mso]><!-->
                                        <a href="{reset_url}" style="display: inline-block; padding: 14px 40px; background-color: #C9184A; color: #ffffff; text-decoration: none; font-weight: bold; font-size: 16px; border-radius: 6px;">Clique Aqui</a>
                                        <!--<![endif]-->
                                    </td>
                                </tr>
                            </table>

                            <p style="margin: 0; color: #6b7280; font-size: 14px; line-height: 1.6;">
                                Se você não solicitou essa redefinição de senha, pode ignorar este email com segurança. Sua senha permanecerá inalterada.
                            </p>
                        </td>
                    </tr>

                    <!-- Link alternativo -->
                    <tr>
                        <td style="padding: 0 40px 32px 40px;">
                            <table role="presentation" cellspacing="0" cellpadding="0" border="0" width="100%" style="background-color: #f9fafb; border-radius: 6px;">
                                <tr>
                                    <td style="padding: 16px;">
                                        <p style="margin: 0; color: #6b7280; font-size: 12px;">
                                            Se o botão não funcionar, copie e cole este link no seu navegador:
                                        </p>
                                        <p style="margin: 8px 0 0 0;">
                                            <a href="{reset_url}" style="color: #C9184A; font-size: 12px; word-break: break-all;">{reset_url}</a>
                                        </p>
                                    </td>
                                </tr>
                            </table>
                        </td>
                    </tr>

                    <!-- Footer -->
                    <tr>
                        <td style="background-color: #f9fafb; padding: 20px 40px; text-align: center; border-top: 1px solid #e5e7eb;">
                            <p style="margin: 0; color: #9ca3af; font-size: 12px;">
                                Este email foi enviado pelo SoundScore.<br>
                                Se você tiver alguma dúvida, entre em contato com nossa equipe de suporte.
                            </p>
                        </td>
                    </tr>
                </table>
            </td>
        </tr>
    </table>
</body>
</html>
"""

    async def send_password_reset_email(self, to_email: str, reset_token: str) -> bool:
        """
        Send password reset email.

        Args:
            to_email: Recipient email address
            reset_token: The password reset token

        Returns:
            True if email was sent successfully, False otherwise
        """
        reset_url = f"{settings.frontend_url}/reset-password?token={reset_token}"

        if not settings.resend_api_key:
            print(f"[DEV MODE] Password reset link: {reset_url}")
            return True

        html_content = self._get_password_reset_email_html(reset_url)

        try:
            params: resend.Emails.SendParams = {
                "from": "SoundScore <noreply@soundscore.com.br>",
                "to": [to_email],
                "subject": "Redefinir sua senha - SoundScore",
                "html": html_content,
            }
            resend.Emails.send(params)
            return True
        except Exception as e:
            print(f"Failed to send password reset email: {e}")
            return False


email_service = EmailService()
